"""Deterministic stratified sampling from the open training stream only."""
import gzip
import json
from collections import defaultdict
from infra_assets import ROOT, BASE, sha

HERE = ROOT/"experiments/m1-infra0"
SOURCE = ROOT/"experiments/m1-core5d/evidence"

def rows(pattern):
    return {r["i"]:r for p in sorted(SOURCE.glob(pattern)) for r in map(json.loads,gzip.open(p))}

def freeze():
    natural = rows("train-V2-*.gz")
    pairs = rows("pairs-train-*.gz")
    worlds = json.load(gzip.open(SOURCE/"panel.gz"))["train"]
    def order(i):
        return worlds[i]["family"]
    def spread(pool,n):
        seq=sorted(pool,key=order)
        return seq if len(seq)<=n else [seq[j*len(seq)//n] for j in range(n)]
    strata=defaultdict(list)
    for i,r in natural.items():
        if r["terminal"] is None: kind="unresolved"
        elif (r["turns"] or 0)>=8: kind="long"
        elif any(q.get("grouped") for q in r["queries"]): kind="multidraw"
        elif any(q.get("conditional") and q["used"] for q in r["queries"]): kind="conditional"
        else: kind="ordinary"
        strata[kind].append(i)
    picked={k:spread(v,20) for k,v in strata.items()}
    seen={i for v in picked.values() for i in v}
    for i in spread(set(natural)-seen,96-len(seen)):
        picked[next(k for k,v in strata.items() if i in v)].append(i)
    cf=defaultdict(list)
    for i,r in pairs.items():
        outcomes=r.get("outcomes")
        if not outcomes: kind="no_pair"
        elif not all(o.get("matched") and o.get("utility") is not None for o in outcomes):kind="unmatched"
        else:
            trace=[a for t,a in natural[i]["trace"] if t==r["turn"]]
            kind="natural_reuse" if any(o.get("steps")==trace for o in outcomes) else "two_continuations"
        cf[kind].append(i)
    paired={k:spread(v,16) for k,v in cf.items()}
    panel=json.load(open(SOURCE/"relic-panel.json"))
    files=[SOURCE/"panel.gz",SOURCE/"relic-panel.json",*SOURCE.glob("train-V2-*.gz"),*SOURCE.glob("pairs-train-*.gz")]
    data=dict(base=BASE,natural=picked,pairs=paired,native=panel["replay"],source_sha256={p.name:sha(p) for p in files})
    (HERE/"panel.json").write_text(json.dumps(data,indent=2)+"\n")

if __name__=="__main__":
    freeze()
