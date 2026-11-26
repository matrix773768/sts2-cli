"""Family-clustered estimates using selection worlds disjoint from comparison worlds."""
from collections import Counter
from pathlib import Path
import sys
import numpy as np
from design import LOGS, jobs, read, write

UNITS={"single":["g2","single_atk","single_def"],"plan":["g2","plan_atk","plan_def"],
       "combined":["g2","search","single_atk","single_def","plan_atk","plan_def"]}


def records():
    rows=[read(p) for d in sorted(LOGS.glob("n4b-finalcore-*")) for p in sorted(d.glob("*.json.gz"))]
    keys=[(r["id"],r["counter"]) for r in rows]
    if len(keys)!=len(set(keys)):
        raise ValueError("Duplicate family condition")
    expected={(j["id"],n,j["split"],j["family"]) for j in jobs() for n in j["counts"]}
    if {(r["id"],r["counter"],r["split"],r["family"]) for r in rows}!=expected:
        raise ValueError("Primary cohort differs from the fixed family manifest")
    return sorted(rows,key=lambda r:(r["id"],r["counter"] or 0))


def vector(r,block,budget,key,field="utility"):
    ys=[]
    for w in r["worlds"][block]:
        rec=w["results"][str(budget)]
        y=rec["outcomes"][rec["refs"][key]]
        if field=="win":
            val=int(y["status"]=="predicted_win")
        elif field=="net":
            val=(r["history"][0][0] if r["history"] else r["h"])["hp"]-y["terminal"]["hp"]
        elif field=="severe":
            initial=(r["history"][0][0] if r["history"] else r["h"])["hp"]
            val=int(initial-y["terminal"]["hp"]>=initial/2)
        else:
            val=y[field]
        ys.append(val)
    return np.array(ys,dtype=float)


def interval(pairs):
    grouped={}
    for family,value in pairs:
        grouped.setdefault(family,[]).append(value)
    x=np.array([np.mean(values) for values in grouped.values()])
    if not len(x):
        return None
    indices=np.random.default_rng(402).integers(len(x),size=(3000,len(x)))
    return dict(mean=float(x.mean()),ci=np.quantile(x[indices].mean(1),[.025,.975]).tolist(),families=len(x))


def assess(rows,budget):
    out=[]
    for r in rows:
        if r["stop"]!="complete" or str(budget) not in r["worlds"]["reference"][0]["results"]:
            continue
        for label,opts in UNITS.items():
            choice=max(opts,key=lambda k:vector(r,"selection",budget,k).mean())
            sel=vector(r,"selection",budget,opts[-2])-vector(r,"selection",budget,opts[-1])
            delta=vector(r,"reference",budget,opts[-2])-vector(r,"reference",budget,opts[-1])
            chosen=vector(r,"reference",budget,choice)
            base=vector(r,"reference",budget,"g2")
            search=vector(r,"reference",budget,"search")
            costs={}
            for block in ("selection","reference"):
                costs[block]=sum(sum(ys["seconds"] for sig,ys in rec["outcomes"].items() if sig in {rec["refs"][k] for k in opts})
                    for w in r["worlds"][block] if (rec:=w["results"][str(budget)]))
            out.append(dict(id=r["id"],family=r["family"],counter=r["counter"],unit=label,chosen=choice,
                selected_gap=float(sel.mean()),gap=float(delta.mean()),se=float(delta.std(ddof=1)/len(delta)**.5),
                replicated=bool(sel.mean()*delta.mean()>0),gain=float((chosen-base).mean()),
                search_gain=float((chosen-search).mean()),teacher_se=float((chosen-base).std(ddof=1)/len(base)**.5),
                win_gain=float((vector(r,"reference",budget,choice,"win")-vector(r,"reference",budget,"g2","win")).mean()),
                net_gain=float((vector(r,"reference",budget,choice,"net")-vector(r,"reference",budget,"g2","net")).mean()),
                severe_gain=float((vector(r,"reference",budget,choice,"severe")-vector(r,"reference",budget,"g2","severe")).mean()),
                costs=costs,distinct=len({tuple(tuple(s) for s in r["paths"][k]) for k in opts})))
    summary={}
    for unit in UNITS:
        sample=[x for x in out if x["unit"]==unit]
        if not sample:
            continue
        summary[unit]=dict(n=len(sample),replicated=sum(x["replicated"] for x in sample),
            nonzero=sum(bool(x["gap"]) for x in sample),avg_se=float(np.mean([x["se"] for x in sample])),
            distinct=float(np.mean([x["distinct"] for x in sample])),seconds=sum(x["costs"]["selection"]+x["costs"]["reference"] for x in sample),
            **{k:interval([(x["family"],x[k]) for x in sample]) for k in ("gain","search_gain","win_gain","net_gain","severe_gain")})
    return dict(rows=out,summary=summary)


def report(rows):
    out={}
    for split in sorted({r["split"] for r in rows}):
        subset=[r for r in rows if r["split"]==split]
        out[split]={str(b):assess(subset,b) for b in (0,24)}
    return out


if __name__=="__main__":
    rows=records()
    natural=[read(p) for p in sorted((LOGS/"n4b-natural-final").glob("*.json.gz"))]
    dest=Path(sys.argv[1])
    if dest.exists():
        raise FileExistsError(dest)
    write(dest,report(rows+natural))
