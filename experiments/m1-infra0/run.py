"""Run one fixed-total-work treatment. Timers span interpreter launch through gzip close."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import perf_counter_ns as clock
from infra_assets import ROOT, sha, verify_inputs

HERE=Path(__file__).resolve().parent
PARENT=ROOT/"experiments/m1-core5d/evidence"

def run(a):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",a.tag):raise ValueError("Invalid run tag")
    verify_inputs()
    panel=json.loads((HERE/"panel.json").read_bytes())
    for name,value in panel["source_sha256"].items():
        if sha(PARENT/name)!=value:raise ValueError(f"Changed input: {name}")
    if a.kind=="pairs" and a.arm!="V2":raise ValueError("Counterfactual continuation requires V2 high")
    ids=sorted(i for group in panel[a.kind].values() for i in group)
    if a.smoke:ids=[154] if a.kind=="natural" else [65]
    if len(set(ids))!=len(ids) or a.workers>len(ids):raise ValueError("Invalid assignments")
    run_dir=ROOT/"logs/infra0-runs"/a.tag
    run_dir.mkdir(parents=True,exist_ok=False)
    tasks=[]
    for worker in range(a.workers):
        folder=run_dir/f"worker-{worker}"
        (folder/"tmp").mkdir(parents=True)
        (folder/"evidence").mkdir()
        shutil.copyfile(PARENT/"panel.gz",folder/"evidence/panel.gz")
        task=dict(smoke=a.smoke,kind=a.kind,arm=a.arm,mode=a.mode,ids=ids[worker::a.workers],folder=str(folder))
        (folder/"task.json").write_text(json.dumps(task))
        tasks.append(task)
    def execute(task):
        folder=Path(task["folder"])
        env={k:v for k,v in os.environ.items() if not k.startswith(("STS2_CORE","CORE5","I1_"))}
        env.update(PYTHONDONTWRITEBYTECODE="1",PYTHONHASHSEED="0",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
        start=clock()
        with (folder/"worker.log").open("wb") as log:
            result=subprocess.run([sys.executable,"-B",str(HERE/"worker.py"),str(folder/"task.json")],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
        end=clock()
        (folder/"process.json").write_text(json.dumps(dict(start=start,end=end,exit=result.returncode)))
        result.check_returncode()
        return start,end
    start=clock()
    with ThreadPoolExecutor(max_workers=a.workers) as pool: intervals=list(pool.map(execute,tasks))
    receipts=[]; closed=[]; records=[]
    for task,(launch,end) in zip(tasks,intervals):
        folder=Path(task["folder"])
        worker=json.loads((folder/"worker.json").read_bytes())
        output=folder/"evidence"/worker["closed"]["file"]
        rows=list(map(json.loads,gzip.open(output)))
        if sorted(r["i"] for r in rows)!=sorted(task["ids"]):raise ValueError("Lost/duplicate root")
        records.extend(rows)
        valid=sum(bool(r.get("terminal")) if a.kind=="natural" else
            len(r.get("outcomes",[]))==2 and all(o.get("matched") and o.get("utility") is not None for o in r["outcomes"]) for r in rows)
        receipts.append(dict(ids=task["ids"],valid=valid,file_sha256=sha(output),bytes=worker["closed"]["bytes"],
             worker_wall_s=(worker["closed"]["at"]-launch)/1e9,cleanup_s=(end-worker["closed"]["at"])/1e9))
        closed.append(worker["closed"]["at"])
    elapsed=(max(closed)-start)/1e9
    qs=[q for r in records for q in r.get("queries",[])]
    totals=dict(valid=sum(w["valid"] for w in receipts),valid_C=sum(len(r["states"]) for r in records if r.get("terminal")),
        decisions=sum(r.get("actions",0) for r in records),full_policies=sum(q["full_policies"] for q in qs),
        attempted_policies=sum(q["attempted_policies"] for q in qs))
    if a.kind=="pairs":
        totals={"valid":totals["valid"],"complete_conditional_plans":sum(len(r.get("plans",[])) for r in records),
                "matched_realized_sides":sum(o.get("matched",False) and o.get("utility") is not None
                    for r in records for o in r.get("outcomes",[]))}
    summary=dict(treatment=vars(a),production_wall_s=elapsed,process_worker_s=sum(b-a for a,b in intervals)/1e9,
        production_worker_s=sum(w["worker_wall_s"] for w in receipts),workers=receipts,totals=totals,
        per_wall_second={k:v/elapsed for k,v in totals.items()})
    (run_dir/"result.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("kind",choices=["natural","pairs"])
    parser.add_argument("arm",choices=["V2","V2low"])
    parser.add_argument("mode",choices=["baseline","aggregate","diagnostic"])
    parser.add_argument("--workers",type=int,choices=[1,2,4],default=1)
    parser.add_argument("--smoke",action="store_true")
    run(parser.parse_args())
