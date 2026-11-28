"""Cost-sensitive paired decisions on held-out families and separate repeat worlds."""
from statistics import mean
from collections import Counter
import sys,time
import numpy as np
from paths5h import *
from evidence5h import cluster

def main():
    tick=time.perf_counter()
    sel=read(E/"selection.json")
    roots=[r for r in read(E/"labels.json") if r["split"]=="dev"]
    hist=read(E/"historical.json")
    family=[r["family"] for r in roots]
    predictions={k:v["active"]["delta"] for k,v in hist.items()}
    for a in sel["entries"]:predictions[a]=read(E/(a+".json"))["best"]["active"]["delta"]
    gains={}
    reports={}
    rng=np.random.default_rng(5829)
    for a,est in predictions.items():
        assert len(est)==len(roots)
        actions=[(False if a=="v2" else r["disagree"] if a=="long" else p>0) for r,p in zip(roots,est)]
        gains[a]=[mean(r["ys"])*int(k) for r,k in zip(roots,actions)]
        parts={}
        for part in ("all","disagreement","representative","repeat"):
            ids=[i for i,r in enumerate(roots) if part=="all" or r["role"]==part or (part=="repeat" and len(r["repeat"])==4)]
            if not ids:continue
            ys=np.array([mean(roots[i]["repeat" if part=="repeat" else "ys"]) for i in ids])
            choose=np.array(actions)[ids]
            gain=ys*choose
            parts[part]=dict(gain=cluster(gain,rng),regret=mean(np.maximum(ys,0)-gain),switches=int(sum(choose)),
                             rmse=float(np.mean((np.array(est)[ids]-ys)**2)**.5),
                             positive=int(sum(gain>0)),negative=int(sum(gain<0)),switch_cost=float(-gain[gain<0].sum()))
        reports[a]=dict(groups=parts,actual_actions=actions,predictions=est)
    comparisons={}
    for model in ("pool","local","interact"):
        control=sel["reps"][model+"-control"]
        active=sel["reps"][model+"-active"]
        comparisons[model]=cluster(np.array(gains[active])-gains[control],rng)
    save(E/"decisions.json",dict(families=family,arms=reports,active_gain_vs_control=comparisons,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
