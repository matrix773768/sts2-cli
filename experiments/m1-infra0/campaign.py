"""One serial budget across both generations; charge failed processes and retain partial files."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from infra_assets import ROOT

HERE=Path(__file__).resolve().parent
RUNS=ROOT/"logs/infra0-runs"
BOOK=RUNS/"infra0b-ledger.jsonl"

def ledger():
    return [json.loads(line) for line in BOOK.read_text().splitlines()] if BOOK.exists() else []

def charge(entry):
    with BOOK.open("a",encoding="utf8") as f:f.write(json.dumps(entry)+"\n")

def treatment(kind,mode,arm="V2",n=1,smoke=False):
    prior=ledger()
    spent=sum(r["worker_s"] for r in prior)
    past=[r["worker_s"] for r in prior if (r.get("kind"),r.get("arm"),r.get("smoke"))==(kind,arm,smoke) and r.get("success")]
    same_n=[r["worker_s"] for r in prior if r.get("success") and (r.get("kind"),r.get("arm"),r.get("smoke"),r.get("n"))==(kind,arm,smoke,n)]
    estimate=max(same_n or past or [480])
    reserve=estimate*(1.35 if n>1 else 1.10)
    if spent+reserve>7200:
        (RUNS/"infra0b-budget-stop.json").write_text(json.dumps(dict(spent_s=spent,next_kind=kind,mode=mode,
            arm=arm,workers=n,reserve_s=reserve)))
        return False
    tag=f"infra0b-{len(prior):03}-{kind}-{mode}"
    folder=RUNS/tag
    script="run.py"
    args=[sys.executable,"-B",str(HERE/script),tag,kind,arm,mode,"--workers",str(n)]
    if smoke:args.append("--smoke")
    tick=time.perf_counter()
    proc=subprocess.Popen(args,cwd=ROOT)
    try:
        proc.wait(timeout=min(2400,max(180,(7200-spent)/n+120)))
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],check=False)
        proc.wait()
    elapsed=time.perf_counter()-tick
    receipt=folder/"result.json"
    data=json.loads(receipt.read_bytes()) if receipt.exists() else {}
    entry=dict(tag=tag,kind=kind,mode=mode,arm=arm,n=n,smoke=smoke,success=proc.returncode==0 and bool(data),
        worker_s=data.get("process_worker_s",elapsed*n),outer_s=elapsed)
    if entry["success"]:
        from formal import semantic_rows
        rows={str(i):v for i,v in semantic_rows(folder).items()}
        entry["semantics"]=rows
        peers=[p for p in prior if p.get("success") and (p.get("kind"),p.get("arm"),p.get("smoke"))==(kind,arm,smoke)]
        if peers and rows!=peers[0]["semantics"]:
            entry["different_ids"]=[i for i in rows if rows[i]!=peers[0]["semantics"].get(i)]
            entry["success"]=False
    charge(entry)
    if not entry["success"]:raise RuntimeError(f"Inspect {tag} before continuing")
    return True

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("group",choices=["high","worlds","secondary","repeat"])
    group=parser.parse_args().group
    jobs=[]
    if group=="high":
        jobs=[(k,m,"V2",1) for k in ("natural","pairs") for m in ("baseline","aggregate")]
    elif group=="worlds":
        jobs=[(k,m,"V2",1) for k in ("initial-train","initial-dev","audit") for m in ("baseline","aggregate")]
    elif group=="repeat":
        jobs=[(k,m,"V2",1) for k in ("natural","pairs","initial-train","initial-dev") for m in ("aggregate","baseline")]
    else:
        jobs=[("natural",m,"V2low",1) for m in ("baseline","aggregate")]+[("natural","baseline","V2",n) for n in (2,4)]
    for job in jobs:
        if not treatment(*job):break
