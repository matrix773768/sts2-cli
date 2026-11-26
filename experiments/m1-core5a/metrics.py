from search5 import FIVE
from study_metrics import readset,describe,paired,ci,utility,rows
from assessment import load_value
from semantic import torch,encode,targets,pack
from statistics import mean,median
from collections import Counter,defaultdict
from pathlib import Path
import gzip,json,sys

E=FIVE/"evidence"
ARMS=("G2","G2search","original","v1","v2")
def key(r):return r["family"],r["seed"]

def measures(records):
    result=describe(records)
    queries=[q for r in records for q in r.get("queries",[])]
    mass=Counter()
    for q in queries:mass.update(q["reference_mass"])
    result.update(reference_complete=sum(q["reference_coverage"]>=1-1e-9 for q in queries),reference_mass=mass,
        outputs=Counter(r.get("status","error") for r in records))
    return result

def pairs_report(records):
    main={key(r):r for r in records if r["policy"]=="v1" and r.get("terminal")}
    counts=Counter();gaps=[];decisions=defaultdict(list);diffs=Counter()
    for alt in records:
        if alt["policy"]!="paired":continue
        counts["attempted"]+=1
        base=main.get(key(alt))
        if not base or not alt.get("terminal"):continue
        counts["resolved"]+=1
        turn=alt["skip"]
        a={c["turn"]:c for c in base["states"]};b={c["turn"]:c for c in alt["states"]}
        if {t:c for t,c in a.items() if t<=turn}!={t:c for t,c in b.items() if t<=turn}:
            raise ValueError("Paired prefix diverged")
        d=utility(base)-utility(alt)
        gaps.append(d)
        decisions[alt["family"]].append(d if alt["gap"]>=0 else -d)
        if alt["gap"]*d>0:counts["correct_sign"]+=1
        if d:counts["different_utility"]+=1
        if not alt["main_used"]:counts["main_no_intervention"]+=1
        if turn+1 in a and turn+1 in b and a[turn+1]!=b[turn+1]:
            counts["distinct_C"]+=1
            x,y=a[turn+1],b[turn+1]
            if x["hp"]!=y["hp"]:diffs["player_hp"]+=1
            if [e["hp"] for e in x["enemies"]]!=[e["hp"] for e in y["enemies"]]:diffs["enemy_hp"]+=1
            if x["powers"]!=y["powers"]:diffs["powers"]+=1
            if x["card_state"]!=y["card_state"]:diffs["card_zones"]+=1
    return dict(counts=counts,observed_differences=diffs,model_preference_gain=ci([mean(v) for v in decisions.values()]))

def likelihood(records):
    torch.set_num_threads(1)
    data=[(encode(c),c["hp"],r["terminal"]["hp"],r["status"]=="death")
          for r in records if r.get("terminal") for c in r["states"]]
    features,hp,end,dead=zip(*data)
    labels=targets(torch.tensor(hp),torch.tensor(end),torch.tensor(dead))
    scores={}
    for name,path in (("v1",FIVE.parent/"m1-core4/evidence/v1.pt"),("v2",E/"v2.pt")):
        net=load_value(path)
        with torch.inference_mode():
            logits=torch.cat([net(*pack(features[i:i+64])) for i in range(0,len(data),64)])
            scores[name]=dict(states=len(data),nll=torch.nn.functional.cross_entropy(logits,labels).item(),
                brier=((logits.softmax(-1)[:,0]-torch.tensor(dead).float())**2).mean().item())
    return scores

def report():
    with gzip.open(E/"panels.gz","rt") as f:panel=json.load(f)
    data={a:readset(sorted(E.glob(f"confirm-{a}-*.gz"))) for a in ARMS}
    by={a:{key(r):r for r in records} for a,records in data.items()}
    common=set.intersection(*[{k for k,r in d.items() if r.get("terminal")} for d in by.values()])
    result={}
    for arm,rr in data.items():
        assert len(rr)==288 and set(by[arm])==set(by["G2"])
        valid=[r for r in rr if key(r) in common]
        counts=Counter()
        for r in rr:counts.update(r.get("controller_counts",{}))
        result[arm]=dict(full=measures(rr),all_arm_paired={b:paired(valid,by[b]) for b in ARMS},
            by_seed=[dict(resolved=sum(bool(r.get("terminal")) for r in rr[i:i+96]),
                          wins=sum(r.get("status")=="predicted_win" for r in rr[i:i+96])) for i in (0,96,192)],controller=counts)
    train=readset(sorted(E.glob("train-v1-*.gz")));dev=readset(E.glob("dev-v1-*.gz"))
    specs=[j[1] for j in panel["confirm"]]
    summary=dict(arms=result,v1_continuation_likelihood=likelihood(data["v1"]),common=len(common),confirm=dict(families=len(specs),encounters=len({s["encounter"] for s in specs}),
       size=[min(len(s["deck"]) for s in specs),median(len(s["deck"]) for s in specs),max(len(s["deck"]) for s in specs)],
       max_hp=Counter(s["max_hp"] for s in specs)),train=measures([r for r in train if r["policy"]=="v1"]),
       train_pairs=pairs_report(train),dev_pairs=pairs_report(dev))
    (E/"results.json").write_text(json.dumps(summary,indent=2))
if __name__=="__main__":report()
