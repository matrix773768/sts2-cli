"""Family-paired, complete-episode estimates and exact binary safety bounds."""
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
import sys
import numpy as np
from math import comb
from pilot_protocol import LIMITS, read, write
from teacher import interval

def upper_count(k,n,alpha):
    if k==n:
        return 1.
    lo,hi=0.,1.
    for _ in range(60):
        mid=(lo+hi)/2
        cdf=sum(comb(n,j)*mid**j*(1-mid)**(n-j) for j in range(k+1))
        if cdf>alpha:
            lo=mid
        else:
            hi=mid
    return hi

def harm_upper(harm,benefit,n):
    if not n:
        return None
    hi=upper_count(harm,n,.025)
    lo=1-upper_count(n-benefit,n,.025)
    return hi-lo

def load_rows(dirs):
    rows={}
    runs={}
    for d in dirs:
        runs[d.name]=read(d/"run.json")["seconds"]
        for p in sorted(d.glob("*.json.gz")):
            row=read(p)
            k=(row["family"],row["domain"])
            if k not in rows:
                rows[k]=row
                continue
            base=rows[k]
            if base["anchor"]!=row["anchor"] or base["stop"]!=row["stop"] or len(base["worlds"])!=len(row["worlds"]):
                raise ValueError("different cohort qualification")
            for b,w in zip(base["worlds"],row["worlds"],strict=True):
                if b["world"]!=w["world"] or b["public"]!=w["public"] or set(b["outcomes"])&set(w["outcomes"]):
                    raise ValueError("invalid pairing")
                b["outcomes"].update(w["outcomes"])
    return list(rows.values()),runs

def stats(y):
    win=int(y["status"]=="predicted_win")
    return dict(win=win,utility=y["utility"],severe=int(not win or y["net_loss"]>=y["initial_hp"]/2))

def compare(entries,name,base):
    pairs=defaultdict(list)
    switches=Counter()
    traces=Counter()
    first=[]
    for f,w in entries:
        y,b=(w["outcomes"].get(k) for k in (name,base))
        if not y or not b or y["utility"] is None or b["utility"] is None:
            continue
        sy,sb=stats(y),stats(b)
        for k in sy:
            pairs[k].append((f,sy[k]-sb[k]))
        if sy["win"] and sb["win"]:
            pairs["joint_hp"].append((f,y["net_loss"]-b["net_loss"]))
        switches[f'{sb["win"]}->{sy["win"]}']+=1
        a,old=y["trace"],b["trace"]
        pos=next((i for i,(u,v) in enumerate(zip(a,old)) if u!=v),min(len(a),len(old)))
        traces["diverged" if a!=old else "identical"]+=1
        if a!=old:
            first.append(pos)
    return dict(n=sum(switches.values()),switches=dict(switches),traces=dict(traces),first_divergence_mean=float(np.mean(first)) if first else None,
        joint_n=len(pairs["joint_hp"]),**{k:interval(pairs[k]) for k in ("utility","win","joint_hp","severe")})

def one(rows):
    ws=[(r["family"],w) for r in rows if r["stop"]=="complete" for w in r["worlds"]]
    names=sorted({k for f,w in ws for k in w["outcomes"]})
    sums={}
    for name in names:
        ys=[w["outcomes"][name] for _,w in ws if name in w["outcomes"]]
        ok=[y for y in ys if y["utility"] is not None]
        es=[e for y in ok for e in y["events"]]
        sums[name]=dict(status=dict(Counter(y["status"] for y in ys)),unresolved_reasons=dict(Counter(str(y.get("reason")) for y in ys if y["utility"] is None)),
            wins=sum(stats(y)["win"] for y in ok),severe=sum(stats(y)["severe"] for y in ok),
            decisions=sum(len(y["trace"]) for y in ok),admin=sum(len(y["admin"]) for y in ok),
            queries=len(es)+sum(y["counts"].get("searches",0) for y in ok),
            interventions=sum(e.get("chosen",-1)>=0 for e in es),first_changed=sum(e["a"]!=e["direct"] for e in es),
            graph_stops=dict(Counter(e["stop"] for e in es if "stop" in e)),
            third_selected=sum(e.get("chosen")==2 for e in es),
            transitions=sum(e.get("transitions",0) for e in es)+sum(y["counts"].get("transitions",0) for y in ok),
            seconds=sum(y["seconds"] for y in ok))
    comparisons={k:compare(ws,k,"g2") for k in names if k!="g2"}
    contrasts={f"{a}-{b}":compare(ws,a,b) for a,b in (("plan_budget","q_budget"),("plan_all","search"),
        ("plan_gate","plan_once"),("plan_gate","q_gate"),("plan_gate","plan_all"),("plan_turn","plan_once"),
        ("q_gate","q_all"),("mixed_gate","plan_gate"),("mixed_all","plan_all"),("plan_once128","plan_once"),
        ("pair_once128","pair_once24"),("plan_once128","pair_once128"),("plan_once","pair_once24"),
        ("gate128","plan_gate"),("gate_once","plan_gate")) if a in names and b in names}
    safety=None
    if rows[0]["domain"]=="natural" and "plan_gate" in names:
        risk={}
        for k in ("win","severe"):
            harmful=helpful=n=0
            for _,w in ws:
                a,b=(w["outcomes"][arm] for arm in ("plan_gate","g2"))
                if a["utility"] is None or b["utility"] is None:
                    continue
                d=(stats(a)[k]-stats(b)[k])*(-1 if k=="win" else 1)
                harmful+=d>0
                helpful+=d<0
                n+=1
            risk[k]=dict(harmful=harmful,helpful=helpful,n=n,upper=harm_upper(harmful,helpful,n))
        common=[a["outcomes"]["plan_gate"]["net_loss"]-a["outcomes"]["g2"]["net_loss"] for _,a in ws if
            all(a["outcomes"][k]["status"]=="predicted_win" for k in ("plan_gate","g2"))]
        x=np.array(common)
        hp=float(np.quantile(np.random.default_rng(404).choice(x,(10000,len(x))).mean(1),.95)) if len(x) else None
        safety=dict(binary=risk,hp_upper=hp,limits=LIMITS,passes=len(ws)==len(rows)==risk["win"]["n"] and hp is not None
            and risk["win"]["upper"]<=LIMITS["win_drop"] and risk["severe"]["upper"]<=LIMITS["severe_increase"] and hp<=LIMITS["joint_loss_increase"])
    return dict(requested=len(rows),families=len(set(f for f,w in ws)),worlds=len(ws),coverage=dict(Counter(r["stop"] for r in rows)),
        errors=dict(Counter(r.get("error") for r in rows if r.get("error"))),rejects=sum(sum(r["failures"].values()) for r in rows),
        encounters=dict(Counter(r["encounter"] for r in rows)),arms=sums,vs_g2=comparisons,contrasts=contrasts,safety=safety)

def run(out,dirs):
    if out.exists():
        raise FileExistsError(out)
    t=perf_counter()
    rows,costs=load_rows(dirs)
    groups={domain:one([r for r in rows if r["domain"]==domain]) for domain in sorted({r["domain"] for r in rows})}
    # Include every assigned family exactly once, replacing only unsupported recipes.
    transfer={r["family"]:r for r in rows if r["domain"]=="transfer"}
    for r in rows:
        if r["domain"]=="transfer_repair":
            if transfer[r["family"]]["worlds"]:
                raise ValueError("repair would replace a measured family")
            transfer[r["family"]]=r
    if transfer:
        groups["transfer_qualified_recipes"]=one(list(transfer.values()))
    for r in rows:
        if r["domain"]=="transfer_multi_extended":
            if transfer[r["family"]]["worlds"]:
                raise ValueError("multi-enemy recipe would replace an evaluated family")
            transfer[r["family"]]=r
    if any(r["domain"]=="transfer_multi_extended" for r in rows):
        groups["transfer_all_recipes"]=one(list(transfer.values()))
    write(out,dict(groups=groups,costs=costs,seconds=perf_counter()-t))

if __name__=="__main__":
    run(Path(sys.argv[1]),[Path(p) for p in sys.argv[2:]])
