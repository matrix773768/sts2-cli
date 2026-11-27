"""Serial treatment coordinator. Use only after the machine is released for 0B."""
from argparse import ArgumentParser,Namespace
import gzip
import json
from pathlib import Path
from statistics import mean
from run import run, ROOT
from semantic_check import digest
from summarize import summarize

def semantic_rows(folder):
    semantics={}
    for worker in folder.glob("worker-*"):
        w=json.loads((worker/"worker.json").read_bytes())
        for r in map(json.loads,gzip.open(worker/"evidence"/w["closed"]["file"])):
            r.pop("seconds",None)
            semantics[r["i"]]=digest(r)
    return semantics

def formal(tag):
    import re
    if not re.fullmatch("[a-zA-Z0-9_-]+",tag):raise ValueError("Invalid campaign tag")
    root=ROOT/"logs/infra0-runs"
    campaign=root/tag
    campaign.mkdir(parents=True,exist_ok=False)
    jobs=[]
    for kind,arm in (("natural","V2"),("pairs","V2"),("natural","V2low")):
        for mode in ("baseline","aggregate","aggregate","baseline"):
            jobs.append((kind,arm,mode,1))
    jobs.extend(("natural","V2","baseline",n) for n in (2,4))
    seen={};results=[];spent=0
    for i,(kind,arm,mode,n) in enumerate(jobs):
        predicted=max([r["worker_s"] for r in results if r["kind"]==kind] or [480])
        if spent+1.5*predicted*n>7200:
            (campaign/"budget-stop.json").write_text(json.dumps(dict(spent=spent,next_job=i)))
            break
        name=f"{tag}-{i:02}"
        run(Namespace(tag=name,kind=kind,arm=arm,mode=mode,workers=n,smoke=False))
        folder=root/name
        receipt=json.loads((folder/"result.json").read_bytes())
        spent+=receipt["process_worker_s"]
        semantics=semantic_rows(folder)
        key=(kind,arm)
        if seen.setdefault(key,semantics)!=semantics:raise RuntimeError("Treatment changed paired production records")
        results.append(dict(kind=kind,arm=arm,mode=mode,n=n,worker_s=receipt["process_worker_s"],
            wall_s=receipt["production_wall_s"],rates=receipt["per_wall_second"],details=summarize(folder)))
        (campaign/"ledger.json").write_text(json.dumps(results,indent=2))
        comparisons=[]
        for workload,value_arm in { (row["kind"],row["arm"]) for row in results }:
            group=[r for r in results if (r["kind"],r["arm"])==(workload,value_arm)]
            base=[r["wall_s"] for r in group if r["mode"]=="baseline" and r["n"]==1]
            aggregate=[r["wall_s"] for r in group if r["mode"]=="aggregate" and r["n"]==1]
            if not base:continue
            row=dict(kind=workload,arm=value_arm,baseline_repeats=len(base),aggregate_repeats=len(aggregate))
            if aggregate:row["elapsed_overhead_fraction"]=mean(aggregate)/mean(base)-1
            row["scaling"]=[dict(n=r["n"],speedup=mean(base)/r["wall_s"],efficiency=mean(base)/r["wall_s"]/r["n"])
                for r in group if r["n"]>1]
            comparisons.append(row)
        (campaign/"comparisons.json").write_text(json.dumps(comparisons,indent=2))

if __name__=="__main__":
    parser=ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--combined",action="store_true",help="Use the shared 5D/5E budget")
    args=parser.parse_args()
    if args.combined:
        if args.tag!="infra0b":parser.error("Combined campaign tag is infra0b")
        from campaign import ledger,treatment
        from finish_campaign import finish
        for kind in ("natural","pairs"):
            for mode in ("baseline","aggregate"):
                if not any(r.get("success") and r.get("kind")==kind and r.get("mode")==mode
                           and r.get("arm")=="V2" and not r.get("smoke") for r in ledger()):
                    if not treatment(kind,mode):raise SystemExit("Campaign budget exhausted")
        finish()
    else:formal(args.tag)
