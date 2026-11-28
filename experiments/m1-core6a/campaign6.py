"""Lock the shortlist before confirmation, with balanced execution order across family shards."""
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from common6 import *

DEV=("g2","v2","direct","g2low","low","same32","same24","same48","trim32")
def launch(job):
    stage,arm,index=job
    receipt=E/f"{stage}-{arm}-{index}.json"
    if receipt.exists():return
    result=subprocess.run([sys.executable,"-B",str(HERE/"battle6.py"),stage,arm,str(index)],capture_output=True)
    if result.returncode:raise RuntimeError(f"{job}: "+result.stderr.decode(errors="replace")[-2100:])

def main():
    for seed in (6119,6233):
        while not (E/f"fit-{seed}.json").is_file():time.sleep(3)
    candidates={f"distill-{s}":read(E/f"distill-{s}.json") for s in (6119,6233)}
    key=max(candidates,key=lambda k:(candidates[k]["score"],k))
    save(E/"picked.json",dict(name=key,weight=candidates[key]["sha256"],criterion="0.50 improved top1 + 0.25 improved top2 + 0.25 all top1"))
    if not (E/"clone-selection.json").exists():
        from clone6 import freeze as freeze_clone
        freeze_clone()
    with ThreadPoolExecutor(3) as workers:list(workers.map(launch,[("dev",a,0) for a in DEV]))
    # Use the same 32 development worlds on one worker per run, starting with the baseline.
    for arm in ("v2","same24","trim32","same48","same32"):
        launch(("cal",arm,0))
    cal={a:read(E/f"cal-{a}-0.json")["worker"] for a in ("v2","same24","trim32","same48","same32")}
    matched=min((a for a in cal if a!="v2"),key=lambda a:abs(cal[a]/cal["v2"]-1))
    arms=list(dict.fromkeys(["g2","v2","direct","g2low","low","same32",matched]))
    save(E/"selection.json",dict(weight=key,calibration=cal,matched=matched,arms=arms,panel_sha=sha(E/"confirm.gz"),protocol_sha=sha(HERE/"protocol.md")))
    jobs=[]
    for i in range(10):
        order=arms.copy()
        random.Random(6120+i).shuffle(order)
        jobs.extend(("confirm",a,i) for a in order)
    with ThreadPoolExecutor(4) as workers:list(workers.map(launch,jobs))
if __name__=="__main__":main()
