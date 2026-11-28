"""Independently check the release, frozen partitions, public actions, laws, and world bindings."""
from collections import Counter
import gzip
import json
from pathlib import Path
from panel import HERE,ROOT,slots,PublicPool
from experience import digest,qualify,read_rows,require,sha
from verify2a_common import check_segment

POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"
BEHAVIOR="51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616"
def load(p):return json.loads(p.read_bytes())
def signed(p):
    r=load(p)
    require(r["id"]==digest({k:v for k,v in r.items() if k!="id"}),p.name)
    return r
def validate():
    release=signed(HERE/"release.json")
    for n,h in release["artifacts"].items():require(sha(HERE/n)==h,n)
    split=load(HERE/"splits.json")
    history=json.load(gzip.open(HERE/"history.gz"))
    old=history["core5f"]
    require(len(old["train"])==945 and len(old["dev"])==96 and old==split["core5f"],"5F split")
    used=set().union(*(s["families"] for s in history["sources"].values()))
    require(set(old["train"]+old["dev"])<=used,"missing historic families")
    reserved=[r["family"] for r in json.load(gzip.open(HERE/"reserve.gz"))["train"]]
    natural={}
    train=[]
    dev=[]
    main={}
    panel=json.load(gzip.open(HERE/"panel.gz"))
    require(len({r["family"] for r in panel if "family" in r})==sum("family" in r for r in panel),"root reuse")
    for r,s in zip(panel,slots(),strict=True):require(all(r[k]==v for k,v in s.items()),"slot order")
    assigned_seeds=set()
    order=["train","dev",*sorted(x for x in release["editions"] if x.startswith("reserve-")),"main","repeat"]
    for ed in order:
        data=HERE/ed
        plan=signed(data/"plan.json")
        manifest=signed(data/"manifest.json")
        ref=release["editions"][ed]
        require(ref["manifest"]==manifest["id"] and ref["plan"]==plan["id"]==manifest["plan_id"],"release ancestry")
        require(plan["runtime"]==load(HERE.parent/"m1-infra1h5/data/plan.json")["runtime"],"H5 runtime")
        is_nat=ed not in ("main","repeat")
        if is_nat:
            views=signed(data/"public/index.json")
            require(views["id"]==ref["public"] and views["dataset"]==manifest["id"],"public parent")
            require(plan["cohort_sha256"]==sha(HERE/(ed+".gz")),"cohort bytes")
            cohort=json.load(gzip.open(HERE/(ed+".gz")))
            part=cohort["protocol"]["split"]
            scheduled=iter(cohort[part])
        else:
            require(plan["panel"]==sha(HERE/"panel.gz") and plan["protocol_id"]==digest(plan["protocol"]),"protocol id")
            for n,h in plan["code"].items():require(sha(HERE/n)==h,"paired source hash")
            if ed=="main":pools={s:PublicPool(s) for s in ("dev","train")}
            else:
                require(plan["parent"]==release["editions"]["main"]["manifest"],"repeat ancestry")
                expected=sorted((i for i,r in main.items() if r[0]),key=lambda i:panel[i]["repeat_rank"])
        valid=total=0
        for s in manifest["shards"]:
            p=data/s["file"]
            require(sha(p)==s["sha256"] and load(p.parent/"receipt.json")==s,"shard receipt")
            shard_valid=0
            if is_nat:
                v=data/"public"/(s["shard"]+".gz")
                require(sha(v)==views["files"][s["shard"]],"public hash")
                obs=iter(read_rows(v))
            for task,r in zip(s["tasks"],read_rows(p),strict=True):
                ok=r["eligible"]
                c=r["trajectory"]
                require(task==r["task_id"] and r["run_id"]==plan["id"] and r["policy_id"]==POLICY,"row identity")
                require(r["native_audit"]=="not_run" and r["native_receipt"] is None,"audit label")
                if is_nat:
                    source=next(scheduled)
                    f=r["family"]
                    require(f==source["family"]==digest(sorted(x["id"] for x in r["spec"]["deck"])) and f not in used,"natural composition")
                    require(ed.startswith("reserve-") or f not in reserved,"reserved family")
                    if ed.startswith("reserve-"):require(f==reserved[cohort["protocol"]["offset"]+total],"reserve order")
                    used.add(f)
                    require(r["spec"]==source["spec"] and r["split"]==part and r["behavior_id"]==BEHAVIOR,"frozen opening/behavior")
                    require(task==digest([plan["id"],"natural",part,f,r["spec"],0,False]) and task not in natural,"natural task")
                    require(qualify(c,r)==ok,"strict natural admission")
                    public=next(obs)
                    require(public["task_id"]==task,"public task")
                    if ok:
                        check_segment(public["segments"][0],c)
                        (dev if part=="dev" else train).append(f)
                    natural[task]=(f,part,ok)
                else:
                    slot=r["slot"]
                    reg=panel[slot]
                    require(r["suffix_behavior_id"]==BEHAVIOR and r["behavior_id"]==plan["protocol_id"],"conditional behavior")
                    require(task==digest([plan["id"],slot,reg.get("natural_task_id")]),"conditional task")
                    if r["family"]:
                        require(natural[r["natural_task_id"]][:2]==(r["family"],r["split"]) and r["public_prefix"]==reg["prefix"],"root mapping")
                    if ed=="main":
                        require(slot==total,"main order")
                        if r["family"]:
                            pre,reason=pools[r["split"]].prefix(reg,r["turn"],r["role"]=="difference")
                            require(pre==r["public_prefix"],"natural public root")
                        main[slot]=(ok,p,task)
                    else:
                        require(slot==expected[total] and main[slot][2]==r["original_task_id"],"repeat registration")
                        parent=next(read_rows(main[slot][1]))["trajectory"]
                        if c.get("plans"):require(c["plans"]==parent["plans"],"repeat plans")
                        c["natural_pair"]=parent["natural_pair"]
                    for j,w in enumerate(c.get("worlds",[])):
                        seed=((ed=="repeat")<<29)+(slot<<21)+(j<<18)+int(digest(["2a-world",ed,slot,j])[:5],16)%262144
                        require(seed==w["seed"] and seed not in assigned_seeds,"world namespace")
                        assigned_seeds.add(seed)
                    if ok:
                        require(qualify(c,dict(kind="conditional",worlds=4)),"strict coupled admission")
                        check_segment(dict(steps=reg["prefix"]["steps"]),c["prefix"])
                        for pair in [c["natural_pair"],*[w["outcomes"] for w in c["worlds"]]]:
                            for side in pair:
                                require(side["steps"][0]["observation"]==reg["prefix"]["root"],"world root")
                                check_segment(dict(steps=side["steps"]),side["trajectory"],True)
                    elif c["status"]=="matched":
                        try:qualified=qualify(c,dict(kind="conditional",worlds=4))
                        except (ValueError,KeyError,IndexError):qualified=False
                        require(not qualified,"unexpected rejection")
                total+=1
                shard_valid+=ok
            if is_nat:require(next(obs,None) is None,"excess public rows")
            require(shard_valid==s["accepted"],"shard denominator")
            valid+=shard_valid
        require(valid==manifest["eligible"] and total==manifest["attempts"],"edition denominator")
        if is_nat:require(next(scheduled,None) is None,"unaccounted natural task")
        print(f"{ed}: {valid}/{total}",flush=True)
    require(split["new_train_rank"]==train and split["primary_train"]==old["train"]+train[:3151] and split["extended_train"]==train[3151:],"training scale")
    require(dev==split["new_dev_eligible"] and set(split["new_dev_attempts"])=={f for f,s,_ in natural.values() if s=="dev"},"development isolation")
if __name__=="__main__":validate()
