"""Targeted conditional-search diagnosis and independent regular-host reload, if budget remains."""
import json
import pstats
import subprocess
import sys
import time
from campaign import HERE,ROOT,RUNS,charge,ledger,treatment
from formal_tables import emit

def finish():
    book=ledger()
    if not any(r.get("kind")=="audit" and r.get("mode")=="aggregate" and r["success"] for r in book):
        raise ValueError("No validated audit workload")
    if not any(r.get("kind")=="audit" and r.get("mode")=="diagnostic" for r in book):
        treatment("audit","diagnostic")
    if sum(r["worker_s"] for r in ledger())+20<7200 and not any(r["kind"]=="native" for r in ledger()):
        tick=time.perf_counter()
        ret=subprocess.run([sys.executable,"-B",str(HERE/"native.py"),"infra0b-native"],cwd=ROOT,timeout=120)
        charge(dict(kind="native",worker_s=time.perf_counter()-tick,success=ret.returncode==0))
        ret.check_returncode()
    # Complete the reverse-order audit pair and retest the scaling curve only
    # if the joint ledger can reserve the entire pair. The first scaling pass
    # showed >100% two-worker efficiency and substantial four-worker imbalance.
    for kind,jobs in (("audit",[("aggregate",1),("baseline",1)]),
                      ("natural",[("baseline",4),("baseline",2)])):
        def matching(mode,n):
            return [r for r in ledger() if r.get("kind")==kind and r.get("arm")=="V2"
                    and r.get("mode")==mode and r.get("n")==n and not r.get("smoke")]
        groups=[matching(mode,n) for mode,n in jobs]
        if any(not g or any(not r["success"] for r in g) for g in groups):continue
        pending=[(mode,n) for (mode,n),g in zip(jobs,groups) if len(g)==1]
        reserve=sum(1.35*matching(mode,n)[0]["worker_s"] for mode,n in pending)
        if sum(r["worker_s"] for r in ledger())+reserve>7200:continue
        for mode,n in pending:
            if not treatment(kind,mode,n=n):break
    emit()
    out=HERE/"evidence/formal"
    native=RUNS/"infra0b-native/native.json"
    if native.exists():(out/"native.json").write_bytes(native.read_bytes())
    for r in ledger():
        if r.get("mode")!="diagnostic" or not r["success"]:continue
        source=RUNS/r["tag"]/"worker-0/diagnostic.prof"
        profiler=pstats.Stats(str(source))
        rows=[]
        for (path,line,fn),(primitive,calls,self_s,cumulative,_) in profiler.stats.items():
            if "/experiments/" not in path.replace("\\","/"):continue
            rows.append(dict(source=path.replace("\\","/").split("/experiments/")[-1],line=line,function=fn,calls=calls,
                primitive_calls=primitive,self_s=self_s,cumulative_s=cumulative))
        (out/"diagnostic-functions.json").write_text(json.dumps(sorted(rows,key=lambda x:-x["self_s"]),indent=2))

if __name__=="__main__":finish()
