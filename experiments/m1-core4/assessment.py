"""Predeclared family-paired full-combat evaluation and mechanism probes."""
from train_value4 import *
from statistics import mean
from collections import defaultdict
from core4_roots import panels

def ci(v):
    if not v:return None
    a=np.asarray(v,dtype=float);rng=np.random.default_rng(4401)
    return dict(n=len(v),mean=float(a.mean()),ci=np.quantile(rng.choice(a,(10000,len(a))).mean(1),[.025,.975]).tolist())

def utility(r):
    return -50 if r["status"]=="death" else payoff(torch.tensor(r["hp"]-r["terminal"]["hp"]),torch.tensor(r["max_hp"])).item()

def summary(out):
    t=perf_counter();torch.set_num_threads(1)
    rr=defaultdict(dict)
    for f in sorted(out.glob("test-*.gz")):
        arm=f.name.split("-")[1]
        for r in rows(f):rr[arm][r["family"]]=r
    report={}
    for k,records in rr.items():
        pairs=[(r,rr["G2"][j]) for j,r in records.items() if r.get("terminal") and rr["G2"].get(j,{}).get("terminal")]
        q=[q for r in records.values() for q in r.get("queries",[])]
        report[k]=dict(attempted=len(records),resolved=len(pairs),wins=sum(r["status"]!="death" for r,b in pairs),
            utility_delta=ci([utility(r)-utility(b) for r,b in pairs]),
            win_delta=ci([int(r["status"]!="death")-int(b["status"]!="death") for r,b in pairs]),
            common_win_hp_delta=ci([r["terminal"]["hp"]-b["terminal"]["hp"] for r,b in pairs if r["status"]==b["status"]=="predicted_win"]),
            actions=sum(r.get("actions",0) for r in records.values()),queries=len(q),interventions=sum(x["used"] for x in q),
            qualified=sum(x.get("reference_coverage",0)>=1-1e-9 for x in q),search_plays=sum(x["calls"]for x in q))
        if k=="G2search":
            legacy=out/"reference-cost.json"
            counts=json.loads(legacy.read_text())["counts"] if legacy.exists() else {}
            report[k].update(queries=counts.get("searches"),search_plays=counts.get("transitions"),interventions=None)
        if k not in ("v0","v1"):report[k]["qualified"]=None
    model_metrics={}
    for arm,cont in (("v0","G2"),("v1","v0")):
        net=load_value(out/(arm+".pt"));points=[(c,r)for r in rr[cont].values() if r.get("terminal") for c in r["states"]]
        feats=[encode(c) for c,r in points];hp=torch.tensor([c["hp"]for c,r in points])
        y=targets(hp,torch.tensor([r["terminal"]["hp"]for c,r in points]),torch.tensor([r["status"]=="death"for c,r in points]))
        bymask={}
        for mask in ("full","future_enemy","pile_position","persistent"):
            with torch.no_grad():
                pred=[]
                for i in range(0,len(feats),64):
                    g,x,m=pack(feats[i:i+64])
                    if mask=="future_enemy":
                        m&=~((x[:,:,F["enemy"]]>0)&((x[:,:,F["depth"]]>0)|(x[:,:,F["edge"]]>0)))
                    if mask=="pile_position":x[:,:,[F[k] for k in ("hand","spent","bag","top","bottom","discard","position","layer","until_play","until_turn")]]=0
                    if mask=="persistent":m&=~((x[:,:,F["power"]]>0)|(x[:,:,F["relic"]]>0))
                    pred.append(net(g,x,m))
                z=torch.cat(pred);risk=z.softmax(-1)[:,0]
                bymask[mask]=dict(n=len(y),nll=functional.cross_entropy(z,y).item(),brier=((risk-(y==0).float())**2).mean().item(),
                    mean_risk=risk.mean().item(),actual_risk=(y==0).float().mean().item())
        model_metrics[arm]=bymask
    # Mechanism strata defined only by opening public enemy rules (held-out from training vs familiar).
    training=set()
    for f in [*(HERE.parent/"m1-core3/evidence").glob("fights*.gz"),*out.glob("nat*.gz"),*out.glob("on*.gz")]:
        for r in rows(f):
            if r.get("split","train")=="train":training.update(e["species"]for c in r["states"]for e in c["enemies"])
    strata=defaultdict(list);cases=[]
    for j,r in rr["v1"].items():
        base=rr["G2"][j]
        if not r.get("terminal") or not base.get("terminal"):continue
        s={e["species"] for c in base["states"] for e in c["enemies"]}
        group="unseen_species" if s-training else "seen_species" if s else "no_C"
        delta=utility(r)-utility(base);strata[group].append(delta)
        cases.append(dict(family=j,delta=delta,base_hp=base["terminal"]["hp"],hp=r["terminal"]["hp"]))
    return dict(arms=report,models=model_metrics,strata={k:ci(v) for k,v in strata.items()},
        largest_losses=sorted(cases,key=lambda x:x["delta"])[:5],seconds=perf_counter()-t)

def load_value(path):
    net=Value();net.load_state_dict(torch.load(path,weights_only=True));return net.eval()
if __name__=="__main__":
    out=Path(sys.argv[1]);(out/"summary.json").write_text(json.dumps(summary(out),indent=2))
