from panel import *
from assessment import utility,ci
from statistics import mean,median
from collections import Counter,defaultdict
def arm(group,name):
    return sorted([r for p in E.glob(f"{group}-{name}-*.gz") for r in records(p)],key=lambda r:r["i"])
def stats(rs):
    q=[q for r in rs for q in r["queries"]];n=len(q);ok=[r for r in rs if r["terminal"]]
    wins=[r for r in ok if r["status"]=="predicted_win"]
    mass=Counter()
    for x in q:mass.update(x["reference_mass"])
    return dict(n=len(rs),term=len(ok),wins=len(wins),cap=sum(r["status"]=="active" for r in rs),
      errors=sum(r["status"]=="error" for r in rs),severe=sum(r["status"]=="death" or r["hp"]-r["terminal"]["hp"]>=r["hp"]/2 for r in ok),
      utility=mean(map(utility,ok)),signed_loss=mean(r["hp"]-r["terminal"]["hp"] for r in ok),
      win_loss=mean(r["hp"]-r["terminal"]["hp"] for r in wins) if wins else None,
      turns=mean(r["turns"] for r in rs if r.get("turns") is not None) if any(r.get("turns") for r in rs) else None,
      partial_loss=[r["hp"]-r["last_hp"] for r in rs if not r["terminal"] and r.get("last_hp") is not None],
      queries=n,ref=sum(x["reference_coverage"]>=1-1e-9 for x in q),cand=sum(x["coverage"]>=1-1e-9 for x in q),
      used=sum(x["used"] for x in q),execution=Counter(x.get("result") for x in q if x["used"]),
      ref_mass=mass,calls=sum(x["calls"] for x in q))
def paired(a,b):
    base={(r["family"],r["seed"]):r for r in b};fam=defaultdict(list);win_deltas=defaultdict(list);hp=[];loss=[];flips=[0,0]
    for x in a:
        y=base[x["family"],x["seed"]]
        if not x["terminal"] or not y["terminal"]:continue
        fam[x["family"]].append(utility(x)-utility(y))
        win=x["status"]=="predicted_win";old=y["status"]=="predicted_win"
        win_deltas[x["family"]].append(int(win)-int(old))
        if win and old:hp.append(x["terminal"]["hp"]-y["terminal"]["hp"])
        if win!=old:flips[int(old)]+=1
        loss.append(y["terminal"]["hp"]-x["terminal"]["hp"])
    return dict(utility=ci([mean(v) for v in fam.values()]),win_delta=ci([mean(v) for v in win_deltas.values()]),common_wins=len(hp),win_hp=mean(hp) if hp else None,
        delta_loss=mean(loss),n=len(loss),flips=flips)
def report():
    panel=json.load(gzip.open(E/"panel.gz","rt"));result={}
    for group,names in (("fresh",["5A","base","medium","high","V1high"]),("high",["G2","G2search","5A","base","high"]),("historical",["base","ref768"])):
        data={a:arm(group,a) for a in names}
        if group=="historical":
            data["5A"]=[r for f in (FIVE/"evidence").glob("confirm-v2-*.gz") for r in records(f)]
        result[group]={}
        for a,rs in data.items():
            assert len(rs)==len(panel[group])
            result[group][a]=stats(rs)|dict(paired={b:paired(rs,v) for b,v in data.items()})
            costs=[json.loads(f.read_bytes()) for f in E.glob(f"{group}-{a}-*.json")]
            result[group][a]["seconds"]=sum(costs) if costs else None
            if group=="high":
                for hard in (True,False):result[group][a]["hard" if hard else "other"]=stats([r for r in rs if panel[group][r["i"]]["hard"]==hard])
    oracle=list(records(E/"oracle.gz"));beams=[r for p in E.glob("beam-*.gz") for r in records(p)]
    verified={r["world"]["family"] for r in oracle if r["reference"]}
    result["oracle"]=dict(tiers=[dict(status=Counter(r["tiers"][i]["search_status"] for r in oracle),
        cumulative=sum(bool(r["tiers"][i]["incumbent"]) for r in oracle),
        transitions=sum(r["tiers"][i].get("transitions") or 0 for r in oracle)) for i in range(3)],
        beam=Counter(r["status"] for r in beams),beam_validation=Counter(r["validation"]["status"] for r in beams if "validation" in r),
        verified=len(verified|{r["world"]["family"] for r in beams if r.get("validation",{}).get("status")=="native_win"}))
    cfs=list(records(E/"counterfactual.gz"));result["cf"]={}
    for k in {r["reason"] for r in cfs}:
        ds=[r["delta"] for r in cfs if r["reason"]==k and r["delta"] is not None]
        result["cf"][k]=dict(delta=ci(ds),better=sum(x>0 for x in ds),worse=sum(x<0 for x in ds))
    (E/"results.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":report()
