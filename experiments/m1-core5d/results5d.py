"""Summaries retain root pairing and bootstrap whole composition families."""
import gzip,json
from collections import Counter,defaultdict
from statistics import mean
from time import perf_counter
from panel5d import E,HERE,FIVE,rows,load
from metrics5b import stats,paired,ci
from deploy5b import load_net,Evaluator
from semantic import torch

def group(pattern):
    return [r for path in sorted(E.glob(pattern+".gz")) for r in rows(path)]

def eligible(r):
    return "outcomes" in r and all(o.get("matched") and o.get("utility") is not None for o in r["outcomes"])

def training(group_name):
    natural=group(group_name+"-V2-*")+group(group_name+"2-V2-*")
    pairs=group("pairs-"+group_name+"-*")+group("pairs-"+group_name+"2-*")
    kept=[r for r in pairs if eligible(r)]
    c=[c for r in natural if r["terminal"] for c in r["states"]]
    return dict(roots=len(natural),natural_status=Counter(r["status"] for r in natural),
       natural_C=len(c),turns=Counter(s["turn"] for s in c),pair_attempts=len(pairs),
       pairs=len(kept),pair_gaps=Counter(r.get("skip") or ("mismatch or unresolved" if "outcomes" in r else "error")
                               for r in pairs if not eligible(r)),
       same_first=sum(r["same_first"] for r in kept),nonintervention=sum(not r["intervened"] for r in kept),
       actual_C_C=sum(all(o["realized"] is not None for o in r["outcomes"]) for r in kept),
       plans_with_terminal=sum(any(z[0]!="C" for z in p["law"]) for r in kept for p in r["plans"]),
       multi_successor_plans=sum(len(p["law"])>1 for r in kept for p in r["plans"]),
       nonzero=sum(r["outcomes"][0]["utility"]!=r["outcomes"][1]["utility"] for r in kept),
       common_death=sum(all(o["status"]=="death" for o in r["outcomes"]) for r in kept))

def score_shared():
    t=perf_counter();torch.set_num_threads(1)
    evals=[Evaluator(load_net(p,n)) for p,n in ((FIVE/"evidence/v2.pt","V2"),(E/"v3.pt","V3"))]
    records=[]
    for r in group("pairs-dev-*")+group("pairs-dev2-*"):
        if not eligible(r):continue
        scores=[]
        for ev in evals:
            values=ev(r["states"],r)
            scores.append([sum(p*(values[key] if k=="C" else u) for k,key,u,p in a["law"]) for a in r["plans"]])
        assert max(abs(x["v2"]-v) for x,v in zip(r["plans"],scores[0]))<.001
        u=[o["utility"] for o in r["outcomes"]]
        picks=[int(s[1]>s[0]) for s in scores]
        records.append(dict(family=r["family"],seed=r["seed"],plans=[p["label"] for p in r["plans"]],scores=scores,
                            picks=picks,utility=u,delta=u[picks[1]]-u[picks[0]]))
    with gzip.open(E/"shared-scores.gz","wt") as out:json.dump(records,out)
    family=defaultdict(list)
    for r in records:family[r["family"]].append(r["delta"])
    return dict(n=len(records),different=sum(a!=b for a,b in (r["picks"] for r in records)),
        better=sum(r["delta"]>0 for r in records),worse=sum(r["delta"]<0 for r in records),
        paired=ci([mean(v) for v in family.values()]),seconds=perf_counter()-t)

def teacher(name):
    data=[r for f in sorted(E.glob(name+"-*.gz")) for r in load(f)]
    by=defaultdict(lambda:defaultdict(list));switches=0;ok=0;gaps=Counter()
    for r in data:
        if r.get("same_deployed"):by["population"][r["family"]].append(0);continue
        w=r["worlds"]
        if len(w)!=4 or not all(eligible(x) for x in w):
            gaps[r.get("skip") or ("error" if r.get("error") else "world mismatch")]+=1;continue
        ds=[a["utility"]-b["utility"] for a,b in (row["outcomes"] for row in w)]
        # First two worlds select a switch only for the exploratory experiment.
        switch=mean(ds[:2])<0;switches+=switch;ok+=1
        for field,val in (("deployed_minus_other",mean(ds[2:])),("heldout_switch_gain",-mean(ds[2:]) if switch else 0.),
                          ("selection_switch_gain",max(0.,-mean(ds[:2]))),("population",mean(ds[2:]))):
            by[field][r["family"]].append(val)
    return dict(roots=len(data),eligible=ok,same=sum(bool(r.get("same_deployed")) for r in data),gaps=gaps,
        switched=switches,estimates={k:ci([mean(x) for x in v.values()]) for k,v in by.items()})

def report():
    data={};panel=load(E/"panel.gz")["confirm"]
    keys={(w["family"],w["spec"]["seed"]) for w in panel}
    arms=("G2","G2search","high","V1","V2low","V2","V3low","V3")
    for name in arms:
        rs=group("confirm-"+name+"-*")
        assert len(rs)==len(keys)==96 and {(r["family"],r["seed"]) for r in rs}==keys
        data[name]=rs
    measures={}
    for arm,rs in data.items():
        q=[x for r in rs for x in r["queries"]]
        measures[arm]=stats(rs)|dict(
            timing=sum(json.loads(p.read_bytes()) for p in E.glob("confirm-"+arm+"-*.time.json")),
            attempts=sum(x.get("attempted_policies",0) for x in q),full=sum(x.get("full_policies",0) for x in q),
            settled=sum(x.get("settled_ends",0) for x in q),ends=sum(x.get("policy_ends",0) for x in q),
            pairs={k:paired(rs,data[k]) for k in arms if k!=arm})
    cost={}
    for name in ("V2","V2low","V3","V3low"):
        costs=group("cost-"+name+"-*")
        if not costs:continue
        assert all(any(r["family"]==k["family"] and r["seed"]==k["seed"] and k["terminal"]==r["terminal"]
                       for k in data[name]) for r in costs)
        cost[name]=dict(n=len(costs),worker_seconds=json.loads((E/f"cost-{name}-0.time.json").read_bytes()),
                        battle_seconds=sum(r["seconds"] for r in costs))
    result=dict(arms=measures,cost=cost,train=training("train"),dev=training("dev"),
                teacher=teacher("teacher"),reference=teacher("reference"),shared=score_shared())
    (E/"results.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":report()
