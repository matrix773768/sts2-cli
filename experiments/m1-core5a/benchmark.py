"""End-to-end paired development runs in counterbalanced order, including Python startup."""
import sys,json,time,subprocess,gzip
from pathlib import Path
from statistics import mean
HERE=Path(__file__).resolve().parent

def benchmark(out):
    out.mkdir(parents=True,exist_ok=False)
    runs=[];reference=None
    for i,arm in enumerate(("slow","fast","fast","slow")):
        path=out/str(i);t=time.perf_counter()
        subprocess.run([sys.executable,str(HERE/"produce.py"),str(path),"dev",arm,"0","0","1"],check=True)
        wall=time.perf_counter()-t
        with gzip.open(path/"rows.gz","rt") as f:rows=list(map(json.loads,f))
        observed=[(r["family"],r["seed"],r["status"],r["actions"],r["states"],r["terminal"],
                   [(q["turn"],q["coverage"],q["reference_coverage"],q["used"],q.get("result"),
                     q["candidate_mass"],q["reference_mass"]) for q in r["queries"]]) for r in rows]
        if reference is None:reference=observed
        qs=[q for r in rows for q in r["queries"]]
        runs.append(dict(arm=arm,wall=wall,matches=sum(a==b for a,b in zip(observed,reference,strict=True)),
                  calls=sum(q["calls"] for q in qs),**json.loads((path/"cost.json").read_bytes())))
    result=dict(runs=runs,speedup=mean(r["wall"] for r in runs if r["arm"]=="slow")/
                mean(r["wall"] for r in runs if r["arm"]=="fast"))
    (out/"benchmark.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":benchmark(Path(sys.argv[1]))
