"""Family-paired outcomes, public-law coverage, allocations and worker costs."""
from pathlib import Path
from collections import Counter
from statistics import mean
import json,gzip
from panel5c import E,HERE,OUT
from metrics5b import stats,paired,arm as historical
def read(paths):
    return [r for p in paths for r in map(json.loads,gzip.open(p))]
def main():
    panel=json.load(gzip.open(E/"protocol.gz"))
    result={}
    for group in ("fresh","regression"):
        keys=[(w["family"],w["spec"]["seed"]) for w in panel[group]]
        arms={}
        for name in ("base","medium","high","referenceOnly","V2complete","V1complete"):
            if group=="regression" and name=="V1complete":
                continue
            if group=="regression" and name in ("base","medium","high"):
                pool=historical("fresh",name)
                rows=[r for r in pool if (r["family"],r["seed"]) in keys]
                paths=[]
            else:
                paths=sorted(E.glob(f"{group}-{name}-*.gz")) if name.endswith("complete") else [E/f"{group}-{name}.gz"]
                rows=read(paths)
            assert len(rows)==len(keys) and sorted((r["family"],r["seed"]) for r in rows)==sorted(keys)
            arms[name]=rows
            q=[q for r in rows for q in r["queries"]]
            timing=[json.loads((OUT/p.stem/"seconds.json").read_bytes()) for p in paths]
            result.setdefault(group,{})[name]=stats(rows)|dict(
                mean_battle_seconds=mean(r["seconds"] for r in rows),worker_seconds=sum(timing) if paths else None,
                host_peak=max((r.get("host_peak",0) for r in rows),default=0),
                python_peak=max((r.get("python_peak",0) for r in rows),default=0),
                new_interface={k:sum(x.get(k,0) for x in q) for k in ("policy_requests","policy_calls","policy_ends","settled_ends","full_policies","attempted_policies","grouped","conditional")},
                conditional_used=sum(bool(x.get("conditional")) and x["used"] for x in q))
        for a,rows in arms.items():
            result[group][a]["paired"]={b:paired(rows,baseline) for b,baseline in arms.items() if a!=b}
    (E/"results.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":
    main()
