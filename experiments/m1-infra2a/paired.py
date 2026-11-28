"""Freeze production identities and run budgeted four-lane windows in slot order."""
import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from panel import HERE,ROOT,freeze,slots
from experience import digest,read_rows,require,sha
from produce_batch import write,exclusive,provenance

WORK=ROOT/"logs/infra2a"
def load(p):return json.loads(p.read_bytes())
def spend():
    seconds=sum(load(p)["worker_seconds"] for p in HERE.glob("*/shards/natural-*/receipt.json"))
    seconds+=sum(load(p)["seconds"] for p in WORK.glob("*/projection.json"))
    seconds+=sum(load(p)["seconds"] for p in WORK.glob("*/lane-*.json"))
    seconds+=sum(load(p)["seconds"] for p in WORK.glob("*/**/failed.json"))
    for p in [WORK/"panel-cost.json",WORK/"engineering.json"]:
        if p.exists():seconds+=load(p)["seconds"]
    return seconds

def setup(phase):
    out=HERE/phase
    for d in ("shards",".pending"):(out/d).mkdir(parents=True,exist_ok=True)
    runtime=provenance(ROOT/"logs/hotsearch-h5")
    require(runtime==load(HERE.parent/"m1-infra1h5/data/plan.json")["runtime"],"H5 drift")
    proto=dict(registration=sha(HERE/"registration.json"),version="m1-infra2a-1",phase=phase,root_budget=128,suffix="h5-tactical32-0",
               worlds=4,seeds="phase bit 29, slot bits 21-28, ordinal bits 18-19, hashed low bits",
               panel_sha256=sha(HERE/"panel.gz"),sources={s:load(HERE/s/"manifest.json")["id"] for s in ("dev","train")})
    plan=dict(protocol=proto,protocol_id=digest(proto),runtime=runtime,panel=proto["panel_sha256"],
              code={n:sha(HERE/n) for n in ("condition_worker.py","worlds.py","panel.py","paired.py","verify2a_common.py")})
    if phase=="repeat":plan["parent"]=load(HERE/"main/manifest.json")["id"]
    plan["id"]=digest(plan)
    p=out/"plan.json"
    if p.exists():require(load(p)==plan,"paired identity changed")
    else:write(p,plan)
    return plan

def window(phase,ids):
    out=HERE/phase
    missing=[i for i in ids if not (out/"shards"/f"slot-{i:03d}/receipt.json").exists()]
    def lane(group):
        if not group:return
        path=WORK/phase/("lane-"+uuid4().hex)
        path.parent.mkdir(parents=True,exist_ok=True)
        start=time.time()
        with path.with_suffix(".log").open("xb") as log:
            p=subprocess.run([sys.executable,"-B",HERE/"condition_worker.py",phase,*map(str,group)],stdout=log,stderr=subprocess.STDOUT,
                             env=os.environ|dict(OMP_NUM_THREADS="1",MKL_NUM_THREADS="1"))
        write(path.with_suffix(".json"),dict(start=start,seconds=time.time()-start,ids=group,exit=p.returncode))
        require(p.returncode==0,"lane failed: "+str(path))
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lane,[missing[i::4] for i in range(4)]))

def seal(phase,plan,ids):
    out=HERE/phase
    shards=[load(out/"shards"/f"slot-{i:03d}/receipt.json") for i in ids]
    for s in shards:require(sha(out/s["file"])==s["sha256"],"paired shard changed")
    manifest=dict(schema="sts2.hotsearch.paired.v2",plan_id=plan["id"],attempts=len(ids),eligible=sum(s["accepted"] for s in shards),shards=shards)
    manifest["id"]=digest(manifest)
    p=out/"manifest.json"
    if p.exists():require(load(p)==manifest,"different sealed panel")
    else:write(p,manifest)

def main():
    with exclusive(WORK/"paired.lock"):
        from register import register
        register()
        if not (HERE/"panel.gz").exists():
            start=time.perf_counter()
            freeze()
            write(WORK/"panel-cost.json",dict(seconds=time.perf_counter()-start))
        plan=setup("main")
        window("main",list(range(48)))
        from results2a import window_report
        observation=window_report()
        p=HERE/"window48.json"
        if not p.exists():write(p,observation)
        avg=observation["worker_seconds"]/48
        available=7200-spend()
        # Use the common reserve before cutting the formal panel; sizes are fixed multiples of four.
        target=min(192,48+4*max(0,int(available/(4*max(avg,0.01)))))
        dispatch=HERE/"main/dispatch.json"
        if dispatch.exists():target=load(dispatch)["target"]
        else:write(dispatch,dict(plan=plan["id"],target=target,available_seconds=available,window_seconds_per_slot=avg))
        ids=list(range(target))
        window("main",ids[48:])
        seal("main",plan,ids)
        plan=setup("repeat")
        order=sorted(ids,key=lambda i:slots()[i]["repeat_rank"])
        eligible=[i for i in order if load(HERE/"main/shards"/f"slot-{i:03d}/receipt.json")["accepted"]]
        count=min(32,max(0,int((7200-spend()-10)/max(avg,0.01))))
        repeat=eligible[:count]
        dispatch=HERE/"repeat/dispatch.json"
        if dispatch.exists():repeat=load(dispatch)["slots"]
        else:write(dispatch,dict(plan=plan["id"],slots=repeat,remaining_seconds=7200-spend()))
        window("repeat",repeat)
        seal("repeat",plan,repeat)
if __name__=="__main__":main()
