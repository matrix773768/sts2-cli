"""Replay the frozen N4 zero pairs and distinguish observed reconvergence from saturated returns."""
from collections import Counter
from itertools import combinations
from pathlib import Path
import sys
from time import perf_counter
from design import LOGS,cohort,digest,read,write


def symbol(h,i):
    a=h["actions"][i]
    card=h["hand"][a["card"]] if a["card"] is not None else {}
    return [a["kind"],card.get("id"),card.get("upgrade"),a.get("target_side"),a.get("target")]


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,_=cohort.runtime(out)
    begin=perf_counter()
    records=[]
    try:
        for j in cohort.plan()[:96]:
            i,spec,_,_,_=j
            r=read(LOGS/f"n4-v2-train/{i:03}.json.gz")
            if r["stop"]!="complete":
                continue
            ws=r["blocks"]["paired"]
            for a,b in combinations(map(str,r["options"]),2):
                if any(w["outcomes"][a]["utility"]!=w["outcomes"][b]["utility"] for w in ws):
                    continue
                metrics=[]
                for w in ws:
                    states=[]
                    actions=[]
                    ys=[w["outcomes"][k] for k in (a,b)]
                    for y in ys:
                        lane=host.lane()
                        hist,h,st=cohort.prefix(lane,spec|dict(seed=w["seed"]),w["order"],i%3==1)
                        assert h==r["h"] and hist==r["history"]
                        sig=[]
                        played=[]
                        for ai in y["actions"][:8]:
                            o=host.project(st["observation"])
                            if not o["enemies"]:
                                break
                            played.append(symbol(o,ai))
                            st=cohort.step(lane,st,ai)
                            if st["status"]!="active":
                                break
                            after=host.project(st["observation"])
                            if after["enemies"]:
                                sig.append(digest(after))
                        states.append(sig)
                        actions.append(played)
                        lane.reset()
                    x,y=ys
                    two=len(actions[0])>=2 and len(actions[1])>=2 and actions[0][:2]==actions[1][:2][::-1]
                    join=next((t+1 for t,(p,q) in enumerate(zip(*states)) if p==q),None)
                    metrics.append(dict(seed=w["seed"],both_dead=x["status"]==y["status"]=="death",public_join=join,
                        swapped_two=two,terminal_resource_diff=any(x.get(k)!=y.get(k) for k in ("loss","gold")) or
                        any(x["terminal"].get(k)!=y["terminal"].get(k) for k in ("hp","max_hp","potions")),
                        turn_diff=x["terminal"]["turn"]!=y["terminal"]["turn"]))
                records.append(dict(id=i,a=a,b=b,worlds=metrics))
        repeat=[]
        for j in cohort.plan()[116:]:
            i=j[0]
            r=read(LOGS/f"n4-v2-confirm/{i:03}.json.gz")
            if r["stop"]!="complete":
                continue
            more=read(LOGS/f"n4-v2-repeat-{116 if i<136 else 136}/{i:03}.json.gz")
            for a,b in combinations(map(str,r["options"]),2):
                diffs=[[w["outcomes"][a]["utility"]-w["outcomes"][b]["utility"] for w in x["blocks"]["reference"]] for x in (r,more)]
                repeat.append(dict(id=i,pair=[a,b],k6=diffs[0],k24=diffs[1]))
        write(out/"zeros.json.gz",dict(train=records,confirmation=repeat,seconds=perf_counter()-begin))
    finally:
        host.close()


if __name__=="__main__":
    run(Path(sys.argv[1]))
