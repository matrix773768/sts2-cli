"""Paired family-cluster intervals with both all-attempt and common-terminal denominators."""
from collections import Counter,defaultdict
from statistics import mean
import numpy as np
from common import *

def complete(r):return r["status"] in ("Defeat","Victory")
def win(r):return r["status"]=="Victory"
def loss(r):return r["opening"]-r["end"]
def u(r):return utility(r["opening"],r["end"],r["maximum"],not win(r))

def paired(a,b):
    groups=defaultdict(list)
    both=[]
    swing=Counter()
    for x,y in zip(a,b,strict=True):
        assert (x["family"],x["seed"])==(y["family"],y["seed"])
        g=groups[x["family"]]
        if complete(x) and complete(y):
            g.append(u(x)-u(y))
            if win(x) and win(y):both.append(loss(x)-loss(y))
            swing[int(win(x))-int(win(y))]+=1
    counts=np.array([len(v) for v in groups.values()])
    sums=np.array([sum(v) for v in groups.values()])
    ix=np.random.default_rng(5129).integers(len(groups),size=(10000,len(groups)))
    draws=sums[ix].sum(1)/counts[ix].sum(1)
    return dict(common=int(counts.sum()),families=int((counts>0).sum()),delta=float(sums.sum()/counts.sum()),
                ci=np.quantile(draws,[.025,.975]).tolist(),both_win=len(both),loss_difference=mean(both),
                gained=swing[1],lost=swing[-1],all_win_delta=mean(int(win(x))-int(win(y)) for x,y in zip(a,b)),
                all_completion_delta=mean(int(complete(x))-int(complete(y)) for x,y in zip(a,b)))

def main():
    fit=read(E/"fit.json")
    rows={}
    results={}
    for arm in ["v2",*fit["arms"]]:
        parts=[read(E/f"confirm-{arm}-{i}.json") for i in range(4)]
        rows[arm]=rs=[r for p in parts for r in p["rows"]]
        ok=[r for r in rs if complete(r)]
        assert len(rs)==192 and len({(r["family"],r["seed"]) for r in rs})==192
        results[arm]=dict(n=len(rs),complete=len(ok),wins=sum(map(win,rs)),mean_u=mean(map(u,ok)),mean_loss=mean(map(loss,ok)),
                          severe=sum(not win(r) or loss(r)>=r["opening"]/2 for r in ok),
                          worker=sum(p["worker_seconds"] for p in parts),queries=sum(r["queries"] for r in rs),
                          closed=sum(r["closed"] for r in rs),interventions=sum(r["interventions"] for r in rs),
                          failures=dict(Counter(r["reason"] for r in rs if not complete(r))))
    comparisons={a:paired(r,rows["v2"]) for a,r in rows.items() if a!="v2"}
    contrasts={a+" minus "+b:paired(rows[a],rows[b]) for a,b in [("td-945","mc-945"),("paired-945","td-945"),("mc-945","mc-128")]}
    save(E/"results.json",dict(arms=results,vs_v2=comparisons,contrasts=contrasts))
if __name__=="__main__":main()
