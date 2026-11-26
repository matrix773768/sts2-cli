"""Small endpoint advantage regressor. A plan followed by G2 is compared to a single G2 action followed by G2."""
from pathlib import Path
import sys
import numpy as np
from teacher import UNITS,interval,records,vector
from design import LOGS,read,write
from time import perf_counter


def features(r,which):
    h=r["h"]
    p=r["endpoints"][which]
    damage=p["damage"]
    block=p["block"]
    enemy=sum(e["hp"]+e["block"] for e in h["enemies"])
    incoming=sum(sum(e["attack_hits"]) for e in h["enemies"])
    missing=max(0,incoming-block)
    hp=p["hp"]
    return np.array([1.,damage/40,damage/max(1,enemy),block/20,min(block,incoming)/15,
        missing/20,max(0,missing-hp+1)/12,float(missing>=hp),hp/60,(hp-missing)/50,
        (p["hp"]-h["hp"])/10,incoming/20,enemy/60,float(p["kind"]=="victory"),
        (damage/max(1,enemy))*min(1.,incoming/max(1,hp)),len(p["steps"])/5])


def fit(rows,lam):
    a=[]
    b=[]
    for r in rows:
        family_weight=1/sum(s["family"]==r["family"] for s in rows)
        for j,name in enumerate(("plan_atk","plan_def")):
            ds=np.concatenate([vector(r,k,0,name)-vector(r,k,0,"g2") for k in ("selection","reference")])
            w=(family_weight/(1+(ds.std(ddof=1)/np.sqrt(len(ds))/15)**2))**.5
            a.append(features(r,j)*w)
            b.append(ds.mean()*w)
    x=np.stack(a)
    return np.linalg.solve(x.T@x+lam*np.eye(x.shape[1]),x.T@np.array(b))


def evaluate(rows,w):
    out=[]
    for r in rows:
        options=UNITS["plan"]
        scores=[0.,float(features(r,0)@w),float(features(r,1)@w)]
        choice=options[int(np.argmax(scores))]
        teacher=max(options,key=lambda k:vector(r,"selection",0,k).mean())
        y=vector(r,"reference",0,choice)
        out.append(dict(id=r["id"],family=r["family"],counter=r["counter"],scores=scores,choice=choice,teacher=teacher,
            gain=float((y-vector(r,"reference",0,"g2")).mean()),regret=float((vector(r,"reference",0,teacher)-y).mean()),
            win_gain=float((vector(r,"reference",0,choice,"win")-vector(r,"reference",0,"g2","win")).mean())))
    return dict(rows=out,**{k:interval([(v["family"],v[k]) for v in out]) for k in ("gain","regret","win_gain")})


def run(out):
    t=perf_counter()
    rs=[r for r in records() if r["stop"]=="complete"]
    train=[r for r in rs if r["split"]=="train"]
    dev=[r for r in rs if r["split"]=="dev"]
    trials=[]
    for lam in (.1,1.,10.):
        w=fit(train,lam)
        validation=evaluate(dev,w)
        trials.append((validation["gain"]["mean"],lam,w))
    _,lam,w=max(trials,key=lambda x:(x[0],x[1]))
    natural=[r for p in sorted((LOGS/"n4b-natural-final").glob("*.gz")) if (r:=read(p))["stop"]=="complete"]
    if len(natural)!=34:
        raise ValueError("Incomplete natural comparison")
    result=dict(penalty=lam,weights=w.tolist(),dev_curve=[[a,b] for a,b,_ in trials],
        confirm=evaluate([r for r in rs if r["split"]=="confirm"],w),natural=evaluate(natural,w),seconds=perf_counter()-t)
    if out.exists():
        raise FileExistsError(out)
    write(out,result)


if __name__=="__main__":
    run(Path(sys.argv[1]))
