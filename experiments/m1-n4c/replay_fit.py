"""Matched projection of existing N4 training-world draws and N4B target advantages."""
from pathlib import Path
from time import perf_counter
import sys
import numpy as np
from deploy import LOGS, cohort, design, digest, features, options, prepared, read, write
from research import rollout
from teacher import vector

def collect(out,validation=False):
    out.mkdir(parents=True,exist_ok=False)
    host,m=design.runtime(out)
    lane=host.lane()
    start=perf_counter()
    try:
        partition="dev" if validation else "train"
        for idx,spec,split,family,_ in [j for j in cohort.plan() if j[2]==partition][:64]:
            row=read(LOGS/f"n4-v2-{partition}/{idx:03}.json.gz")
            audit=dict(id=idx,family=family,split=split,stop=row["stop"],worlds=[])
            try:
                if row["stop"]=="complete":
                    def at(w):
                        return cohort.prefix(lane,spec|dict(seed=w["seed"]),w["order"],idx%3==1)
                    anchor=dict(seed=cohort.seed(family,"anchor",0),order=cohort.permutation(spec["deck"],row["hand"],cohort.seed(family,"anchor-order",0)))
                    hist,h,st=at(anchor)
                    remove=lambda o:{k:v for k,v in o.items() if k!="nunchaku"}
                    if remove(h)!=row["h"] or [[remove(o),a] for o,a in hist]!=row["history"]:
                        raise ValueError("anchor mismatch")
                    c=prepared(m,h,hist)
                    c.project=lane.host.project
                    ps,info=options(lane,c,h,24)
                    direct=int(c.score([(h,c.history)])[0][0].argmax())
                    lane.reset()
                    audit.update(history=hist,h=h,paths=ps,graph=info,direct=direct)
                    if ps:
                        for w in row["blocks"]["reference" if validation else "paired"]:
                            ys=[]
                            for path in ([[digest(h),direct]],*[p["steps"] for p in ps]):
                                history,obs,st=at(w)
                                if history!=hist or obs!=h:
                                    raise ValueError("conditioning drift")
                                ys.append(rollout(lane,m,hist,h,st,path,0))
                                lane.reset()
                            audit["worlds"].append(dict(seed=w["seed"],proposal=w["proposal"],order=w["order"],ys=ys))
                        if any(y["utility"] is None for w in audit["worlds"] for y in w["ys"]):
                            audit["stop"]="unresolved"
                    else:
                        audit["stop"]="no_endpoint"
            except (ValueError,RuntimeError) as e:
                audit.update(stop="error",reason=str(e))
                lane.close()
            write(out/f"{idx:03}.json.gz",audit)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-start))

def examples(folder,partition):
    if partition not in ("train","dev"):
        raise ValueError("unavailable fitting/validation partition")
    target=[]
    families={j["id"]:j["family"] for j in design.jobs() if j["split"]==partition}
    for idx,family in sorted(families.items()):
        for p in sorted(LOGS.glob(f"n4b-finalcore-*/{idx:03}-*.json.gz")):
            r=read(p)
            if (family,partition)!=(r["family"],r["split"]):
                raise ValueError("target partition drift")
            if r["stop"]!="complete":
                continue
            for i,name in enumerate(("plan_atk","plan_def")):
                blocks=("selection","reference") if partition=="train" else ("reference",)
                d=np.concatenate([vector(r,b,0,name)-vector(r,b,0,"g2") for b in blocks])
                target.append((family,(idx,r["counter"]),features(r,i),d))
    ordinary=[]
    allowed={j[0]:j[3] for j in cohort.plan() if j[2]==partition}
    for p in sorted(folder.glob("*.json.gz")):
        r=read(p)
        if allowed.get(r["id"])!=r["family"]:
            raise ValueError("ordinary partition drift")
        if r["stop"]!="complete":
            continue
        for i in range(len(r["paths"])):
            d=np.array([w["ys"][i+1]["utility"]-w["ys"][0]["utility"] for w in r["worlds"]])
            ordinary.append((r["family"],r["id"],features(dict(h=r["h"],endpoints=r["paths"]),i),d))
    fs=[{z[0] for z in dom} for dom in (target,ordinary)]
    if not all(fs) or fs[0]&fs[1]:
        raise ValueError("empty or overlapping domains")
    return target,ordinary

def solve(domains,fraction):
    from collections import Counter
    matrix=np.zeros((16,16))
    response=np.zeros(16)
    size=len({z[0] for z in domains[0]})
    for records,share in zip(domains,(1-fraction,fraction),strict=True):
        counts=Counter(z[0] for z in records)
        for f,_,x,d in records:
            wt=(2*size*share/len(counts)/counts[f]/(1+(d.std(ddof=1)/len(d)**.5/15)**2))
            matrix+=wt*np.outer(x,x)
            response+=wt*x*d.mean()
    return np.linalg.solve(matrix+.1*np.eye(16),response)

def fit(out,folder):
    begin=perf_counter()
    domains=examples(folder,"train")
    ref=solve(domains,0)
    if not np.allclose(ref,read(LOGS/"n4b-plan.json")["weights"]):
        raise ValueError("target-only refit differs from frozen ridge")
    weights=solve(domains,.5)
    curve={}
    for frac in (0,.25,.5,.75,1.):
        coef=solve(domains,frac)
        curve[str(frac)]={k:float(np.mean([(x@coef-d.mean())**2 for _,_,x,d in dom]))
            for k,dom in zip(("target_train","ordinary_train"),domains,strict=True)}
    if out.exists():
        raise FileExistsError(out)
    write(out,dict(weights=weights.tolist(),families=[sorted({z[0] for z in dom}) for dom in domains],
        options=list(map(len,domains)),paired_returns=[sum(len(z[3]) for z in dom) for dom in domains],
        fraction=.5,lambda_ridge=.1,training_mse=curve,seconds=perf_counter()-begin))

def diagnose(out,train,dev):
    from collections import defaultdict
    from teacher import interval
    start=perf_counter()
    fit_rows=examples(train,"train")
    val=examples(dev,"dev")
    if {z[0] for dom in fit_rows for z in dom}&{z[0] for dom in val for z in dom}:
        raise ValueError("validation leakage")
    trials=[]
    for proportion in (.25,.5,1.):
        subsets=[]
        for dom in fit_rows:
            fam=sorted({z[0] for z in dom},key=lambda f:digest(["n4c-curve",f]))
            keep=set(fam[:max(1,round(len(fam)*proportion))])
            subsets.append([z for z in dom if z[0] in keep])
        for mix in (0,.5):
            coef=solve(subsets,mix)
            metrics=[]
            for domain in val:
                roots=defaultdict(list)
                for f,key,x,d in domain:
                    roots[(f,key)].append((float(x@coef),float(d.mean())))
                gains=[]
                errors=[]
                for (f,key),options in roots.items():
                    _,actual=max([(0.,0.),*options],key=lambda z:z[0])
                    gains.append((f,actual))
                    errors.append((f,np.mean([abs(a-b) for a,b in options])))
                metrics.append(dict(gain=interval(gains),mae=interval(errors),roots=len(roots)))
            trials.append(dict(proportion=proportion,mix=mix,train_families=[len({z[0] for z in dom}) for dom in subsets],
                               target=metrics[0],ordinary=metrics[1]))
    if out.exists():
        raise FileExistsError(out)
    write(out,dict(curve=trials,seconds=perf_counter()-start))

if __name__=="__main__":
    if sys.argv[1] in ("collect","validate"):
        collect(Path(sys.argv[2]),sys.argv[1]=="validate")
    elif sys.argv[1]=="curve":
        diagnose(*map(Path,sys.argv[2:]))
    else:
        fit(Path(sys.argv[2]),Path(sys.argv[3]))
