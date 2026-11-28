"""Verify the published edition offline from read-only artifacts, including all actual action menus."""
import gzip,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from experience import digest,qualify,read_rows,require,sha
from produce_batch import tasks
from publish_views import actions

def check_segment(segment,battle,intervention=False):
    steps=segment["steps"]
    require(actions(battle)==[s["index"] for s in steps],"replay indices")
    trace=iter(battle["trace"]);choices=iter(battle["choices"]);bind=[]
    planned={q["turn"] for q in battle.get("queries",[]) if "policy" in q}
    if intervention:planned.add(battle["trace"][0][0])
    for step in steps:
        obs=step["observation"];i=step["index"];f=obs["facts"]
        if f["turn"] in planned:bind.append([obs["view"],i])
        if obs["status"]=="choice":
            choice=next(choices)
            require(0<=i<len(obs["options"]) and obs["options"]==choice["options"] and i==choice["selected"],"choice menu")
        else:
            require(obs["status"]=="active" and 0<=i<len(f["actions"]),"illegal action")
            a=f["actions"][i];t,index,kind,slot,target,side=next(trace)
            require(a["index"]==index==i and f["turn"]==t and a["target"]==target and a["target_side"]==side,"target binding")
            require((kind=="play_card" and a["kind"]=="PlayCard" and slot==a["card"]) or
                    (kind=="end_turn" and a["kind"]=="EndTurn" and slot is None),"action binding")
    require(next(trace,None) is None and next(choices,None) is None,"incomplete menu trace")
    require(bind==[edge[1:] for edge in battle.get("executed_bindings",[])],"evaluated program differs from actual menu")

def verify(data,cohort_path):
    manifest=json.loads((data/"manifest.json").read_bytes());plan=json.loads((data/"plan.json").read_bytes())
    public=json.loads((data/"public/index.json").read_bytes())
    for obj in (manifest,plan,public):require(obj["id"]==digest({k:v for k,v in obj.items() if k!="id"}),"manifest hash")
    require(public["dataset"]==manifest["id"] and manifest["plan_id"]==plan["id"] and sha(cohort_path)==plan["cohort_sha256"],"lineage")
    cohort=json.load(gzip.open(cohort_path))
    todo={t["id"]:t for t in tasks(cohort,plan["id"])}
    require(len({x["family"] for x in cohort["train"]+cohort["open"]})==len(cohort["train"])+len(cohort["open"]),"split collision")
    accepted=0
    for s in manifest["shards"]:
        path=data/s["file"];views=data/"public"/(s["shard"]+".gz")
        require(json.loads((path.parent/"receipt.json").read_bytes())==s and sha(path)==s["sha256"] and sha(views)==public["files"][s["shard"]],"shard integrity")
        count=0
        for task,r,v in zip(s["tasks"],read_rows(path),read_rows(views),strict=True):
            t=todo.pop(task);raw=r["trajectory"]
            require(r["task_id"]==v["task_id"]==task and r["spec"]==t["spec"] and r["run_id"]==plan["id"],"task identity")
            require(r["native_audit"]=="not_run" and r["native_receipt"] is None and r["policy_id"]==s["policy_id"],"qualification label")
            require(qualify(raw,t)==r["eligible"],"admission disagreement")
            if not r["eligible"]:continue
            count+=1
            if r["kind"]=="natural":check_segment(v["segments"][0],raw)
            else:
                seg=iter(v["segments"]);check_segment(next(seg),raw["prefix"])
                for seed,pair in [(None,raw["natural_pair"]),*[(w["seed"],w["outcomes"]) for w in raw["worlds"]]]:
                    for side in pair:
                        actual=next(seg);require(actual["world"]==seed,"mismatched coupling")
                        check_segment(actual,side["trajectory"],True)
                require(next(seg,None) is None,"unexpected suffix")
        require(count==s["accepted"],"receipt count");accepted+=count
    require(not todo and accepted==manifest["eligible"],"incomplete frozen cohort")
    print(f"Verified {manifest['attempts']} tasks, {accepted} eligible records, all sampled-world bindings and public menus.")
if __name__=="__main__":
    release=json.loads((HERE/"release.json").read_bytes())
    require(release["id"]==digest({k:v for k,v in release.items() if k!="id"}),"release catalog")
    for name,h in release["artifacts"].items():require(sha(HERE/name)==h,"evidence hash")
    for edition in release["editions"]:
        base=HERE/edition["path"]
        for filename,field in [("manifest.json","manifest"),("plan.json","plan"),("public/index.json","public")]:
            require(json.loads((base/filename).read_bytes())["id"]==edition[field],"edition reference")
    verify(HERE/"data",HERE/"cohort.json.gz")
    verify(HERE/"capacity",HERE/"capacity-cohort.json.gz")
    first=json.load(gzip.open(HERE/"cohort.json.gz"))
    more=json.load(gzip.open(HERE/"capacity-cohort.json.gz"))
    combined=first["open"]+first["train"]+more["train"]
    require(len({r["family"] for r in combined})==len({r["spec"]["seed"] for r in combined})==1184,"cross-release leakage")
