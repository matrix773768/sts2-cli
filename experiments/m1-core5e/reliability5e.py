"""Independent half-world estimates and empirical influence of the old single-world loss."""
import json,math
from collections import Counter,defaultdict
from statistics import mean,variance
import numpy as np
from panel5e import E
from data5e import read_cases,completed,deltas
from assessment import ci

def old_location(values):
    # Equal-root illustration of the 5D tie thinning, scaled Huber and nonzero signed loss.
    # The shared network/Adam and minibatch normalizations cannot be reconstructed by a scalar regression.
    x=np.asarray(values);nz=x!=0
    candidates=np.arange(-151.,151.1,.25)
    err=np.abs((candidates[:,None]-x)/40)
    huber=np.where(err<1,.5*err**2,err-.5)
    weights=np.where(nz,1.,1/3)
    loss=(huber*weights).sum(1)/weights.sum()
    if nz.any():loss+=.18*np.logaddexp(0,-candidates[:,None]*np.sign(x[nz])/12).mean(1)
    return float(candidates[np.argmin(loss)])
def summary(split):
    all_cases=read_cases(split);cases=[c for c in all_cases if completed(c)]
    metrics=defaultdict(list);families=defaultdict(list);skips=Counter()
    partial_worlds=0;zero_conflicts=0;zeros=0;deaths=death_conflicts=0;diffs=[]
    for case in all_cases:
        if not completed(case):
            reason=case.get("error") or ("incomplete paired execution" if case["worlds"] else "no eligible plan/root")
            skips[reason]+=1;partial_worlds+=len(case["worlds"])
    for case in cases:
        ds=deltas(case);n=len(ds);k=n//2
        for x,w in zip(ds,case["worlds"]):
            if x==0:zeros+=1;zero_conflicts+=any(v!=0 for v in ds)
            if all(o["status"]=="death" for o in w["outcomes"]):
                deaths+=1;death_conflicts+=any(v!=0 for v in ds)
        # Symmetric held-out halves avoid a lucky ordering of a small number of draws.
        se=[];four=[];old=[]
        for sample,target in ((ds[:k],ds[k:]),(ds[k:],ds[:k])):
            m=mean(target)
            se.append(mean((x-m)**2 for x in sample))
            four.append((mean(sample)-m)**2)
            old.append((old_location(sample)-m)**2)
            diffs.append((mean(sample),m))
        metrics["single_mse"].append(mean(se));metrics["half_mse"].append(mean(four))
        metrics["old_mse"].append(mean(old))
        metrics["within_var"].append(variance(ds));metrics["mean_sampling_var"].append(variance(ds)/n)
        families[case["family"]].append(mean(old)-mean(four))
    return dict(attempted=len(all_cases),complete=len(cases),failed=skips,excluded_worlds_started=partial_worlds,
                worlds=sum(len(c["worlds"]) for c in cases),turns=Counter(c["turn"] for c in cases),
                same_first=sum(c["same_first"] for c in cases),incumbent_pairs=sum(c["main"] in [p["label"] for p in c["plans"]] for c in cases),
                nonintervention=sum(not c["intervened"] for c in cases),vary=sum(len(set(deltas(c)))>1 for c in cases),
                single_zero=zeros,zero_in_varying_pair=zero_conflicts,common_deaths=deaths,
                common_death_with_nonzero_sibling=death_conflicts,all_zero=sum(not any(deltas(c)) for c in cases),
                single_rmse=math.sqrt(mean(metrics["single_mse"])),half_rmse=math.sqrt(mean(metrics["half_mse"])),
                sd_single=math.sqrt(mean(metrics["within_var"])),se_mean=math.sqrt(mean(metrics["mean_sampling_var"])),
                old_location_rmse=math.sqrt(mean(metrics["old_mse"])),old_minus_mean_mse=ci([mean(v) for v in families.values()]),
                half_sign_agreement=sum(a*b>0 for a,b in diffs if a and b)/max(1,sum(bool(a and b) for a,b in diffs)),
                both_nonzero_halves=sum(bool(a and b) for a,b in diffs)//2)
def run():
    (E/"reliability.json").write_text(json.dumps({s:summary(s) for s in ("train","dev")},indent=2))
if __name__=="__main__":run()
