"""Run or resume a versioned strict HotSearch cohort. Commit complete shards by atomic rename."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import gzip
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
from experience import digest,qualify,read_rows,require,sha

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SCHEMA="sts2.hotsearch.experience.v1"

def write(path,value):
    tmp=path.with_name(path.name+"."+uuid4().hex+".tmp")
    with tmp.open("x",encoding="utf8",newline="\n") as out:
        json.dump(value,out,ensure_ascii=False,allow_nan=False,separators=(",",":"));out.flush();os.fsync(out.fileno())
    os.replace(tmp,path)

@contextmanager
def exclusive(path):
    # Kernel-held byte lock disappears if the coordinating process dies.
    with path.open("a+b") as f:
        if f.tell()==0:f.write(b"0");f.flush()
        f.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield

def provenance(build):
    b=json.loads((build/"identity.json").read_bytes());bin_dir=build/"bin/Release/net9.0"
    for name,path in [("host",bin_dir/"OfflineSearchHarness.dll"),("hot",bin_dir/"CombatSolver.dll"),("game",ROOT/"lib/sts2.dll")]:
        require(b[name]==sha(path),"runtime differs from build identity: "+name)
    bridge=[ROOT/"logs/infra0-world-inputs/panel.gz",*sorted((ROOT/"experiments/m1-core5d/evidence").glob("train-V2-*.gz"))]
    return dict(bridge_inputs={p.name:sha(p) for p in bridge},build=b,godot=sha(bin_dir/"GodotSharp.dll"),coreclr="9.0.7",python=platform.python_version(),
        torch=importlib.metadata.version("torch"),kernel="1.0.2",sources={p.name:sha(p) for p in
            [HERE/n for n in ("hot_produce.py","condition.py","client.py","models.py","contingent.py","experience.py","produce_batch.py")]},
        g2=sha(ROOT/"logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt"),v2=sha(ROOT/"experiments/m1-core5a/evidence/v2.pt"))

def tasks(cohort,version):
    result=[]
    def add(kind,split,r,worlds,bridge=False):
        t=dict(kind=kind,split=split,family=r["family"],donor=r.get("donor"),spec=r["spec"],worlds=worlds,bridge=bridge)
        t["id"]=digest([version,kind,split,t["family"],t["spec"],worlds,bridge])
        result.append(t)
    for split in ("train","open"):
        for r in cohort[split]:add("natural",split,r,0)
    pool={r["family"]:r for r in cohort["train"]}
    for f in cohort["conditions"]:add("conditional","train",pool[f],4)
    for r in cohort["bridge123"]:add("conditional","bridge",r,4,True)
    require(len(result)==len({t["id"] for t in result}),"duplicate task")
    return result

def shards(jobs,size):
    groups={}
    for t in jobs:groups.setdefault((t["kind"],t["split"]),[]).append(t)
    return [(f"{kind}-{split}-{i//size:04}",a[i:i+size]) for (kind,split),a in groups.items() for i in range(0,len(a),size)]

def mechanism_tags(t,r):
    found={t["spec"]["encounter"],*(c["id"] for c in t["spec"]["deck"])}
    def visit(v):
        if isinstance(v,list):
            for item in v:visit(item)
        elif isinstance(v,dict):
            for k,item in v.items():
                if k in ("affliction","enchantment","species","id") and isinstance(item,str):found.add(item)
                elif isinstance(item,(list,dict)):visit(item)
    # Real public observations and raw C carry card, power, and monster IDs.
    visit(r["states"])
    return sorted(found)

def execute(group,args,plan):
    name,items=group;dest=args.data/"shards"/name
    receipt=dest/"receipt.json"
    if receipt.exists():
        r=json.loads(receipt.read_bytes())
        require(r["tasks"]==[t["id"] for t in items] and sha(dest/"rows.gz")==r["sha256"],"committed shard mismatch")
        return r,True
    attempt=args.work/name/uuid4().hex;attempt.mkdir(parents=True)
    tick=time.perf_counter();write(attempt/"attempt.json",dict(shard=name,started=time.time(),plan=plan["id"]))
    specs=attempt/"specs.json";write(specs,[dict(family=t["family"],spec=t["spec"]) for t in items])
    out=attempt/"production";first=items[0];kind=first["kind"]
    if kind=="natural":
        cmd=[HERE/"hot_produce.py",out,"--specs",specs,"--arm","tactical","--limit","32"]
        source=out/"natural.jsonl.gz"
    else:
        cmd=[HERE/"condition.py",out,"--arm","tactical","--limit","128","--suffix-limit","32","--worlds","4","--retain-trajectory"]
        cmd+=["--ids","123"] if first["bridge"] else ["--hot-pairs","--specs",specs]
        source=out/"worlds.jsonl.gz"
    try:
        with (attempt/"worker.log").open("wb") as log:
            subprocess.run([sys.executable,"-B",*cmd],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                env=os.environ|dict(HOTSEARCH_BUILD=str(args.build),PYTHONDONTWRITEBYTECODE="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1"),check=True)
        ledger=json.loads((out/"ledger.json").read_bytes())
        require(not ledger["diagnostic"],"diagnostic worker")
        policy=ledger["policy"];prov=plan["runtime"]
        require(policy["id"]==digest({k:v for k,v in policy.items() if k!="id"}) and policy["build"]==prov["build"] and
            (policy["g2"],policy["v2"],policy["arm"],policy["rule_calls_per_action_style"],policy["margin"])==(prov["g2"],prov["v2"],"tactical",32,0) and
            all(prov["sources"][k]==v for k,v in policy["python"].items()),"policy drift")
        behavior=digest([policy["id"],kind,128 if kind=="conditional" else 32,first["worlds"],"historical-prefix" if first["bridge"] else "hot-prefix"])
        stage=Path(tempfile.mkdtemp(prefix=name+"-",dir=args.data/".pending"))
        accepted=0;counts=Counter()
        with (stage/"rows.gz").open("xb") as f,gzip.GzipFile(fileobj=f,mode="wb",filename="",mtime=0,compresslevel=6) as z:
            for i,(r,t) in enumerate(zip(read_rows(source),items,strict=True)):
                require(r["family"]==t["family"] and r["policy_id"]==policy["id"] and r["i"]==(123 if t["bridge"] else i),"root identity")
                if kind=="natural":require(r["seed"]==t["spec"]["seed"],"seed mismatch")
                try:eligible=qualify(r,t)
                except (KeyError,IndexError,TypeError,ValueError) as exc:
                    eligible=False;r["admission_error"]=str(exc)
                row=dict(schema=SCHEMA,run_id=plan["id"],task_id=t["id"],kind=kind,split=t["split"],family=t["family"],seed=t["spec"]["seed"],
                    donor=t["donor"],spec=t["spec"],behavior_id=behavior,policy_id=policy["id"],eligible=eligible,native_audit="not_run",
                    native_receipt=None,mechanisms=mechanism_tags(t,r),trajectory=r)
                z.write(json.dumps(row,allow_nan=False,separators=(",",":")).encode()+b"\n")
                accepted+=eligible;counts[r["status"]]+=1
        meta=dict(shard=name,file="shards/"+name+"/rows.gz",sha256=sha(stage/"rows.gz"),kind=kind,split=first["split"],tasks=[t["id"] for t in items],
            accepted=accepted,status=counts,policy_id=policy["id"],behavior_id=behavior,ledger=ledger,worker_seconds=time.perf_counter()-tick)
        write(stage/"receipt.json",meta);stage.rename(dest)
        write(attempt/"finished.json",dict(seconds=meta["worker_seconds"],state="committed"))
        return meta,False
    except Exception as exc:
        write(attempt/"failed.json",dict(seconds=time.perf_counter()-tick,error=str(exc)))
        raise

def with_retry(group,args,plan):
    for attempt in range(args.retries+1):
        try:return execute(group,args,plan)
        except (OSError,subprocess.CalledProcessError):
            if attempt==args.retries:raise

def run(args):
    args.data=args.data.resolve();args.build=args.build.resolve();args.work=args.work.resolve()
    for p in (args.data,args.work,args.data/"shards",args.data/".pending"):p.mkdir(parents=True,exist_ok=True)
    with exclusive(args.work/"coordinator.lock"),exclusive(args.data/"writer.lock"):
        protocol=json.load(gzip.open(args.cohort));runtime=provenance(args.build)
        path=args.data/"plan.json"
        if path.exists():
            plan=json.loads(path.read_bytes())
            require(plan["id"]==digest({k:v for k,v in plan.items() if k!="id"}) and plan["runtime"]==runtime and
                plan["cohort_sha256"]==sha(args.cohort) and plan["shard_size"]==args.size,"resume identity mismatch")
        else:
            plan=dict(schema=SCHEMA,cohort_sha256=sha(args.cohort),protocol=protocol["protocol"],runtime=runtime,
                source_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),shard_size=args.size)
            plan["id"]=digest(plan);write(path,plan)
        jobs=tasks(protocol,plan["id"]);groups=shards(jobs,args.size)
        pending=[g for g in groups if not (args.data/"shards"/g[0]/"receipt.json").exists()]
        # Verify previously committed bytes before resuming. Failed processes leave private attempts only.
        existing=[execute(g,args,plan)[0] for g in groups if g not in pending]
        start=time.time()
        if args.max_shards is not None:pending=pending[:args.max_shards]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            new=[row for row,_ in pool.map(lambda g:with_retry(g,args,plan),pending)]
        receipts=sorted(existing+new,key=lambda r:r["shard"])
        write(args.work/("session-"+uuid4().hex+".json"),dict(start=start,wall=time.time()-start,workers=args.workers,new=[r["shard"] for r in new]))
        if len(receipts)==len(groups):
            require(provenance(args.build)==runtime,"runtime changed during production")
            manifest=dict(schema=SCHEMA,plan_id=plan["id"],attempts=len(jobs),eligible=sum(r["accepted"] for r in receipts),shards=receipts)
            manifest["id"]=digest(manifest)
            path=args.data/"manifest.json"
            if path.exists():require(json.loads(path.read_bytes())==manifest,"sealed manifest differs")
            else:write(path,manifest)
        print(f"{len(receipts)}/{len(groups)} shards committed, {len(new)} new",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("cohort","data","work","build"):p.add_argument(k,type=Path)
    p.add_argument("--workers",type=int,default=3);p.add_argument("--size",type=int,default=16)
    p.add_argument("--max-shards",type=int);p.add_argument("--retries",type=int,default=1)
    a=p.parse_args()
    if a.size<1 or a.workers<1 or a.retries<0 or (a.max_shards is not None and a.max_shards<0):p.error("invalid production size")
    run(a)
