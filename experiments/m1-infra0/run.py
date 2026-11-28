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

def good(w):
    return len(w["outcomes"])==2 and all(o.get("matched") and o.get("utility") is not None for o in w["outcomes"])

def complete(r):
    return len(r["worlds"])==r.get("world_count",-1) and all(good(w) for w in r["worlds"])

def run(a):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",a.tag):raise ValueError("Invalid run tag")
    verify_inputs()
    panel=json.loads((HERE/"panel.json").read_bytes())
    for name,value in panel["source_sha256"].items():
        if sha(PARENT/name)!=value:raise ValueError(f"Changed input: {name}")
    if a.kind=="pairs" and a.arm!="V2":raise ValueError("Counterfactual continuation requires V2 high")
    world=a.kind not in ("natural","pairs")
    input_panel=PARENT/"panel.gz"
    if world:
        if a.arm!="V2":raise ValueError("Condition worlds require the frozen V2 continuation")
        from world_assets import OPEN
        pinned=json.loads((HERE/"world-panel.json").read_bytes())
        for name,value in pinned["sources"].items():
            if sha(OPEN/name)!=value:raise ValueError("Changed open 5E input: "+name)
        for name,value in json.loads((OPEN/"inputs.json").read_bytes())["world_host"]["artifacts"].items():
            if sha(ROOT/"logs/core5e-world-host"/name)!=value:raise ValueError(name)
        input_panel=OPEN/"panel.gz"
        ids=pinned["ids"][a.kind]
        if a.smoke:ids=[75 if a.kind=="initial-train" else ids[0]]
    else:
        ids=sorted(i for group in panel[a.kind].values() for i in group)
        if a.smoke:ids=[154] if a.kind=="natural" else [65]
    sample=getattr(a,"sample",None)
    if sample is not None:
        if not (a.variant or "").startswith("h-") or a.smoke or not 1<sample<len(ids):
            raise ValueError("Expected a bounded subset of an open INFRA panel")
        ids=[ids[j*(len(ids)-1)//(sample-1)] for j in range(sample)]
    if len(set(ids))!=len(ids) or a.workers>len(ids):raise ValueError("Invalid assignments")
    if (getattr(a,"variant",None) or "").startswith("h-") and (ROOT/"logs/infra1h"/("skip-"+a.tag)).exists():
        raise SystemExit("Superseded before worker launch: "+a.tag)
    run_dir=ROOT/"logs/infra0-runs"/a.tag
    run_dir.mkdir(parents=True,exist_ok=False)
    tasks=[]
    for worker in range(a.workers):
        folder=run_dir/f"worker-{worker}"
        (folder/"tmp").mkdir(parents=True)
        (folder/"evidence").mkdir()
        shutil.copyfile(input_panel,folder/"evidence/panel.gz")
        task=dict(smoke=a.smoke,kind=a.kind,arm=a.arm,mode=a.mode,ids=ids[worker::a.workers],folder=str(folder))
        if getattr(a,"variant",None):task["variant"]=a.variant
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
        valid=sum(complete(r) for r in rows) if world else sum(bool(r.get("terminal")) if a.kind=="natural" else
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
    if world:
        worlds=[w for r in records for w in r["worlds"]]
        outs=[o for w in worlds for o in w["outcomes"]]
        totals=dict(attempted_roots=len(records),valid=sum(complete(r) for r in records),
            started_worlds=len(worlds),paired_worlds=sum(len(w["outcomes"])==2 for w in worlds),
            locally_valid_worlds=sum(good(w) for w in worlds),
            admitted_worlds=sum(len(r["worlds"]) for r in records if complete(r)),
            returned_sides=len(outs),terminal_sides=sum(o.get("utility") is not None for o in outs))
    summary=dict(treatment=vars(a),production_wall_s=elapsed,process_worker_s=sum(b-a for a,b in intervals)/1e9,
        production_worker_s=sum(w["worker_wall_s"] for w in receipts),workers=receipts,totals=totals,
        per_wall_second={k:v/elapsed for k,v in totals.items()})
    (run_dir/"result.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("kind",choices=["natural","pairs","initial-train","initial-dev","audit"])
    parser.add_argument("arm",choices=["V2","V2low"])
    parser.add_argument("mode",choices=["baseline","aggregate","diagnostic"])
    parser.add_argument("--workers",type=int,choices=[1,2,4],default=1)
    parser.add_argument("--variant",choices=["batch","batch-attribution","g2-check","shadow","reuse","h-scalar","h-batch","h-engine","h-kernel2","h-kernel3","h-kernel4","h-kernel4-g2","h-kernel5","h-kernel5-g2","h-kernel6","h-kernel6-g2","h-state","h-state-control"])
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--sample",type=int,default=argparse.SUPPRESS)
    run(parser.parse_args())
