"""Single-worker campaign. Each attempt has a separate directory and a charged wall."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=HERE.parent/"m1-infra0"
LOG=ROOT/"logs/infra1h"
RUNS=ROOT/"logs/infra0-runs"
BOOK=LOG/"ledger.jsonl"
E=HERE/"evidence"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def charge(label,args,env=None):
    import msvcrt
    LOG.mkdir(exist_ok=True,parents=True)
    with (LOG/"worker.lock").open("a+b") as lock:
        if lock.tell()==0:lock.write(b"1");lock.flush()
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError:time.sleep(.25)
        try:return _charge(label,args,env)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def _charge(label,args,env=None):
    LOG.mkdir(exist_ok=True,parents=True)
    book=[json.loads(s) for s in BOOK.read_text().splitlines()] if BOOK.exists() else []
    if any(r["label"]==label for r in book):raise ValueError("Attempt already recorded: "+label)
    left=7195-sum(r["seconds"] for r in book)  # leave time to close a process tree at the budget boundary
    if left<1:raise RuntimeError("Campaign budget spent")
    started=time.time()
    start=time.perf_counter()
    with (LOG/(label+".log")).open("xb") as log:
        proc=subprocess.Popen(list(map(str,args)),cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:proc.wait(timeout=left)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],check=False)
            proc.wait()
    row=dict(label=label,seconds=time.perf_counter()-start,exit=proc.returncode,args=list(map(str,args)))
    row.update(start_utc_unix=started,settings={k:v for k,v in (os.environ if env is None else env).items() if k.startswith("INFRA1H_")})
    with BOOK.open("a",encoding="utf8") as f:f.write(json.dumps(row)+"\n")
    print(label,round(row["seconds"],2),row["exit"],flush=True)
    if proc.returncode:raise RuntimeError("See "+str(LOG/(label+".log")))

def run(tag,variant,kind,smoke=False,profile=False,sample=None):
    name="infra1h-"+tag+"-"+kind+"-"+variant
    dependency=LOG/("after-"+name)
    if dependency.exists():
        check=RUNS/dependency.read_text().strip()/"worker-0/verification.json"
        while not check.exists():time.sleep(2)
        if not json.loads(check.read_bytes())["equal"]:raise SystemExit("Prerequisite failed verification")
    if (LOG/("skip-"+name)).exists():
        raise SystemExit("Superseded before worker launch: "+name)
    args=[sys.executable,"-B",OLD/"run.py",name,kind,"V2","aggregate" if profile else "baseline"]
    if variant!="original":args.extend(["--variant",variant])
    if smoke:args.append("--smoke")
    if sample is not None:args.extend(["--sample",str(sample)])
    charge(name,args)
    frozen=json.loads((OLD/"evidence/formal/campaign.json").read_bytes())
    wanted=next(r["semantics"] for r in frozen if r.get("kind")==kind and r["mode"]=="baseline" and r["arm"]=="V2" and not r["smoke"])
    folder=RUNS/name/"worker-0"
    meta=json.loads((folder/"worker.json").read_bytes())
    got={}
    for row in map(json.loads,gzip.open(folder/"evidence"/meta["closed"]["file"])):
        row.pop("seconds",None)
        raw=json.dumps(row,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        got[str(row["i"])]=hashlib.sha256(raw).hexdigest()
    delta={k:[wanted.get(k),v] for k,v in got.items() if wanted.get(k)!=v}
    equal=not delta and bool(got) and (smoke or (sample is not None and len(got)==sample) or got==wanted)
    (folder/"verification.json").write_text(json.dumps(dict(equal=equal,rows=len(got),differences=delta)))
    if not equal:raise ValueError("Production mismatch: "+name)

if __name__=="__main__":
    if sys.argv[1]=="build":charge("build-"+sys.argv[2],[sys.executable,"-B",HERE/"build.py",*sys.argv[2:]])
    elif sys.argv[1]=="run":run(*sys.argv[2:5],smoke="--smoke" in sys.argv[5:],profile="--profile" in sys.argv[5:],sample=next((int(x.split("=")[1]) for x in sys.argv[5:] if x.startswith("--sample=")),None))
    else:charge(sys.argv[1],sys.argv[2:])
