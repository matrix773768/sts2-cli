"""Account at the natural family or paired root level; retain individual failed sides."""
from collections import Counter,defaultdict
import gzip
import json
import statistics
from pathlib import Path
from panel import HERE,ROOT,slots
from experience import read_rows,require,sha,digest
from produce_batch import write
WORK=ROOT/"logs/infra2a"
def load(path):return json.loads(path.read_bytes())
def records(data):
    manifest=load(data/"manifest.json")
    for s in manifest["shards"]:yield from read_rows(data/s["file"])
def union(intervals):
    end=0
    total=0
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,end))
        end=max(end,b)
    return total

def paired_stats(rows):
    strata=defaultdict(lambda:[0,0,0])
    failures=Counter()
    side_failures=Counter()
    sums=Counter()
    means={}
    info=[]
    for r in rows:
        c=r["trajectory"]
        has_root=r["family"] is not None
        ok=r["eligible"]
        for k in ["all",r["split"],"act-"+str(r["act"]),r["role"],"turn-"+str(r["turn"]),
                  "/".join(map(str,(r["split"],r["act"],r["role"],r["turn"])))]:
            for j,v in enumerate([1,has_root,ok]):strata[k][j]+=v
        costs=c.get("cost",{})
        sums.update(costs)
        for w in c.get("worlds",[]):
            sums["admitted_resampled_actual_C" if ok else "partial_resampled_actual_C"]+=sum(len(side.get("trajectory",{}).get("states",[])) for side in w["outcomes"])
        sums["admitted_original_actual_C" if ok else "partial_original_actual_C"]+=sum(len(side.get("trajectory",{}).get("states",[])) for side in c.get("natural_pair",[]))
        sums["recovered_prefix_actual_C"]+=len(c.get("prefix",{}).get("states",[]))
        deltas=[]
        if ok:
            for w in c["worlds"]:
                a,b=w["outcomes"]
                deltas.append(a["utility"]-b["utility"])
            means[str(r["slot"])]=statistics.mean(deltas)
        issues=[]
        if not ok:
            issues=[c.get("reason") or c["status"]]
            failures.update(issues)
        n_pairs=0
        for w in c.get("worlds",[]):
            for side in w["outcomes"]:
                if "reason" in side:issues.append(side["reason"])
            n_pairs+=int(len(w["outcomes"])==2 and all(s.get("public_matched") and s.get("matched") for s in w["outcomes"]))
        original=c.get("natural_pair",[])
        for side in original:
            if "reason" in side:issues.append(side["reason"])
        for pair in [original,*[w["outcomes"] for w in c.get("worlds",[])]]:
            for side in pair:
                if "reason" in side:side_failures[side["reason"]]+=1
        sums["resampled_pairs_attempted"]+=len(c.get("worlds",[]))
        sums["original_pairs_attempted"]+=bool(original)
        info.append(dict(slot=r["slot"],task=r["task_id"],source=r["natural_task_id"],family=r["family"],split=r["split"],act=r["act"],turn=r["turn"],role=r["role"],
                         eligible=ok,cost=costs,errors=issues,world_seeds=[w["seed"] for w in c.get("worlds",[])],complete_resampled_pairs=n_pairs,
                         original_delta=original[0]["utility"]-original[1]["utility"] if len(original)==2 and all("utility" in s for s in original) else None,
                         paired_deltas=deltas,mean=means.get(str(r["slot"]))))
    return dict(strata=dict(strata),failures=failures,side_failures=side_failures,stages=sums,means=means,roots=info,
                changing=sum(len(set(i["paired_deltas"]))>1 for i in info),nonzero=sum(x!=0 for x in means.values()))

def window_report():
    ids=range(48)
    data=HERE/"main/shards"
    rows=(next(read_rows(data/f"slot-{i:03d}/rows.gz")) for i in ids)
    res=paired_stats(rows)
    lanes=[load(p) for p in (WORK/"main").glob("lane-*.json") if set(load(p)["ids"])<=set(ids)]
    seconds=sum(x["seconds"] for x in lanes)
    panel=json.load(gzip.open(HERE/"panel.gz"))[:48]
    scan=sum(r["scan_seconds"] for r in panel)
    seconds+=scan
    n=len(res["means"])
    return res|dict(worker_seconds=seconds,scan_seconds=scan,candidates_scanned=sum(len(r["scans"]) for r in panel),
                    per_eligible=seconds/n if n else None,estimated_192_minutes=seconds/48*192/60,
                    estimated_192_with_32_repeats_minutes=seconds/48*224/60)

def main():
    from paired import spend
    history=json.load(gzip.open(HERE/"history.gz"))
    old=history["core5f"]
    reserved=set().union(*(s["families"] for s in history["sources"].values()))
    natural={}
    train=[]
    dev=[]
    reserve=json.load(gzip.open(HERE/"reserve.gz"))["train"]
    next_reserved={r["family"] for r in reserve}
    require(len(next_reserved)==len(reserve) and not next_reserved&reserved,"reserve history")
    all_new=set()
    mapping={}
    failures=[]
    intervals=[]
    ledger={}
    for edition in ["train","dev",*sorted(p.name for p in HERE.glob("reserve-*") if p.is_dir())]:
        data=HERE/edition
        ident=load(data/"manifest.json")
        stats=Counter()
        tiers=defaultdict(Counter)
        timings=[]
        rows=list(json.load(gzip.open(HERE/(edition+".gz")))[("dev" if edition=="dev" else "train")])
        require(len(rows)==ident["attempts"],"frozen attempt count")
        for r,source in zip(records(data),rows,strict=True):
            f=r["family"]
            require(f==source["family"]==digest(sorted(c["id"] for c in r["spec"]["deck"])),"family identity")
            require(f not in reserved|all_new and (edition.startswith("reserve-") or f not in next_reserved),"cross-release overlap")
            all_new.add(f)
            ok=r["eligible"]
            raw=r["trajectory"]
            mapping[r["task_id"]]=dict(family=f,split=r["split"],eligible=ok,reason=raw.get("reason") or raw.get("admission_error"))
            stats["attempts"]+=1
            stats["eligible"]+=ok
            stats["actual_C" if ok else "rejected_C"]+=len(raw["states"])
            tiers[str(r["spec"]["act"])+" / "+source["source"]]["attempts"]+=1
            tiers[str(r["spec"]["act"])+" / "+source["source"]]["eligible"]+=ok
            if ok:(dev if edition=="dev" else train).append(f)
            else:failures.append(dict(task=r["task_id"],**mapping[r["task_id"]]))
        for s in ident["shards"]:
            l=s["ledger"]
            tick,=(WORK/edition/s["shard"]).glob("*/finished.json")
            start=load(tick.parent/"attempt.json")["started"]
            timings.append((start,start+s["worker_seconds"]))
            stats["worker_seconds"]+=s["worker_seconds"]
            stats["python_cpu"]+=l["python_cpu"]
            stats["host_cpu"]+=l["host"]["cpu"]
            for k,v in [("python_peak_rss",l["python_peak_rss"]),("host_peak_rss",l["host"]["peak_rss"])]:stats[k]=max(stats[k],v)
        projection=load(WORK/edition/"projection.json")["seconds"]
        end=(WORK/edition/"projection.json").stat().st_mtime
        intervals+=timings+[(end-projection,end)]
        natural[edition]=dict(stats)|dict(active_wall=union(timings),projection_seconds=projection,strata=tiers)
    panel=json.load(gzip.open(HERE/"panel.gz"))
    conditional={}
    by_phase={}
    for phase in ("main","repeat"):
        res=paired_stats(records(HERE/phase))
        for r in res["roots"]:
            r["source_admission"]=mapping.get(r["source"])
        lanes=[load(p) for p in (WORK/phase).glob("lane-*.json")]
        processes=[load(p) for p in (WORK/phase).glob("*/end.json")]
        intervals.extend((l["start"],l["start"]+l["seconds"]) for l in lanes)
        res["resources"]=dict(worker=sum(l["seconds"] for l in lanes),cpu=sum(p["cpu"]+p["host"]["cpu"] for p in processes),
                              peak_python=max([p["peak_rss"] for p in processes] or [0]),peak_host=max([p["host"]["peak_rss"] for p in processes] or [0]))
        res["lanes"]=lanes
        res["processes"]=processes
        conditional[phase]=res
        by_phase[phase]=res["means"]
    agreement=[(v,by_phase["main"][k]) for k,v in by_phase["repeat"].items()]
    ledger.update(natural=natural,paired=conditional,candidates_scanned=sum(len(r["scans"]) for r in panel),selected=sum("family" in r for r in panel),
                  scan_cost=load(WORK/"panel-cost.json"),failures=failures,worker_seconds=spend(),worker_limit=7200,
                  active_wall_natural_worlds_and_exports=union(intervals),reassessment_rmse=(statistics.mean((a-b)**2 for a,b in agreement)**0.5 if agreement else None))
    ledger["reserve_families_still_reserved"]=sorted(next_reserved-all_new)
    ledger["engineering"]=load(WORK/"engineering.json") if (WORK/"engineering.json").exists() else None
    ledger["main_dispatch"]=load(HERE/"main/dispatch.json")
    ledger["repeat_dispatch"]=load(HERE/"repeat/dispatch.json")
    write(HERE/"ledger.json",ledger)
    combined=old["train"]+train[:3151]
    require(len(set(combined))==len(combined),"primary collision")
    write(HERE/"splits.json",dict(core5f=old,new_train_rank=train,primary_train=combined,extended_train=train[3151:],
                                  new_dev_attempts=[r["family"] for r in mapping.values() if r["split"]=="dev"],new_dev_eligible=dev))
    artifacts={p.name:sha(p) for p in sorted(HERE.iterdir()) if p.is_file() and p.suffix in (".gz",".py",".json") and p.name!="release.json"}
    editions={p.parent.name:dict(manifest=load(p)["id"],plan=load(p.parent/"plan.json")["id"],
                                 public=load(p.parent/"public/index.json")["id"] if (p.parent/"public/index.json").exists() else None) for p in HERE.glob("*/manifest.json")}
    release=dict(schema="sts2.hotsearch.2a.release.v1",editions=editions,artifacts=artifacts)
    write(HERE/"release.json",release|dict(id=digest(release)))
if __name__=="__main__":main()
