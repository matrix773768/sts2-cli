"""Additional historical full-information BeamSolver profile. Same frozen hard panel."""
from oracle import *
from concurrent.futures import ThreadPoolExecutor
import subprocess
def shard(i):
    out=LOGS/f"5b-beam-{i}";out.mkdir(exist_ok=False)
    host=dc.Host(out,dc.BUILD,dc.config()|{"workers":1});start=perf_counter()
    with gzip.open(E/f"beam-{i}.gz","xt") as f:
        for w in json.load(gzip.open(E/"panel.gz","rt"))["oracle"][i::2]:
            t=perf_counter()
            try:
                with dc.opened(host,w) as (lane,pub,snapshot,audit,_):
                    identity=dc.digest([pub,snapshot,audit])
                    r=lane.request("i1_capture",node_budget=8000)
                    if lane.request("f1_audit")!=audit:raise ValueError("Source mutated")
                row={k:v for k,v in r.items() if k in ("status","reason","boundary","search_cpu_ms","solve_ms","transitions","expanded_nodes","predicted_win","actions")}
                if row["status"]=="complete_win":row["validation"]=dc.witness(host,w,identity,r)
            except (RuntimeError,ValueError,TimeoutError,OSError,KeyError) as e:row=dict(status="error",detail=str(e))
            f.write(json.dumps(dict(world=w,seconds=perf_counter()-t,**row))+"\n");f.flush()
    (E/f"beam-{i}.json").write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":
    if len(sys.argv)>1:shard(int(sys.argv[1]))
    else:
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda i:subprocess.run([sys.executable,__file__,str(i)],check=True),range(2)))
