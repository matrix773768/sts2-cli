"""Freeze strata before timing. Historical suffix length is represented by remaining parent actions."""
import gzip
import json
from collections import defaultdict
from statistics import variance
from world_assets import OPEN,HERE,ROOT,sha

def rows(pattern):
    return {r["i"]:r for p in sorted(OPEN.glob(pattern)) for r in map(json.loads,gzip.open(p))}

def freeze():
    panel={};specs={};pop={}
    for split in ("train","dev"):
        cases=rows(f"worlds-{split}-*.gz")
        parents={}
        for name in {r["source"] for r in cases.values()}:
            for f in (ROOT/"experiments/m1-core5d/evidence").glob(name+"-V2-*.gz"):
                for r in map(json.loads,gzip.open(f)):parents[name,r["i"]]=r
        bins=defaultdict(list)
        for i,r in cases.items():
            parent=parents[r["source"],r["index"]];t=r.get("turn",0)
            p=sum(turn<t for turn,_ in parent["trace"])
            kind=("no_pair" if not r.get("plans") else "error" if r.get("error") else "unmatched"
                if any(not o.get("matched") for w in r["worlds"] for o in w["outcomes"]) else str(r["world_count"]))
            specs[split,i]=dict(i=i,stratum=kind,turn=t,prefix=p,parent_remaining=len(parent["trace"])-p,
                            same_first=r.get("same_first"),skips=r["skips"])
            bins[kind].append(i)
        quota=({"4":5,"8":3,"no_pair":1,"error":2,"unmatched":1} if split=="train" else {"8":4,"error":1,"no_pair":1})
        selected=[]
        for key,items in bins.items():
            ordered=sorted(items,key=lambda i:(specs[split,i]["turn"],specs[split,i]["prefix"],specs[split,i]["same_first"],i))
            size=quota[key]
            selected.extend(ordered[round(j*(len(ordered)-1)/max(size-1,1))] for j in range(size))
        panel["initial-"+split]=sorted(selected)
        pop["initial-"+split]={k:len(v) for k,v in bins.items()}
    archived=rows("audit12-train-*.gz")
    initial=rows("worlds-train-*.gz")
    groups=defaultdict(list)
    for i in archived:
        ds=[w["outcomes"][0]["utility"]-w["outcomes"][1]["utility"] for w in initial[i]["worlds"]]
        groups["noisy" if variance(ds)>0 else "zero"].append(i)
    assert {k:len(v) for k,v in groups.items()}=={"noisy":12,"zero":4}
    panel["audit"]=sorted(sorted(groups["noisy"])[j] for j in (0,5,11))+[min(groups["zero"])]
    pop["audit"]={k:sorted(v) for k,v in groups.items()}
    data=dict(ids=panel,population=pop,selected={k:[specs["dev" if k.endswith("dev") else "train",i] for i in ids] for k,ids in panel.items()},
        sources={f.name:sha(f) for f in sorted(OPEN.glob("*.gz"))})
    (HERE/"world-panel.json").write_text(json.dumps(data,indent=2))
if __name__=="__main__":freeze()
