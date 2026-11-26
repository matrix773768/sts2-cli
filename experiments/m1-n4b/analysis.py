"""Summaries for the preregistered family split; native resources and censored branches stay separate."""
from collections import Counter
from itertools import combinations
from pathlib import Path
from time import perf_counter
import sys
import numpy as np
from design import LOGS,read,write
from teacher import assess,interval,records,report,vector
from learn_menu import outcomes


def compare_units(rs):
    result={}
    for label,subset in (("confirm",[r for r in rs if r["split"]=="confirm"]),("natural",[r for r in rs if r["split"]=="natural"])):
        rows=assess(subset,0)["rows"]
        pairs=[(s,p) for s,p in zip([v for v in rows if v["unit"]=="single"],[v for v in rows if v["unit"]=="plan"],strict=True)]
        result[label]=interval([(s["family"],p["gain"]-s["gain"]) for s,p in pairs])
    return result


def continuation(rs):
    rows=[]
    for r in rs:
        if r["stop"]!="complete" or "24" not in r["worlds"]["reference"][0]["results"]:
            continue
        base=lambda b,k:vector(r,"reference",b,k)
        weak=base(0,"plan_atk")-base(0,"plan_def")
        alt=base(24,"plan_atk")-base(24,"plan_def")
        rows.append(dict(id=r["id"],family=r["family"],counter=r["counter"],split=r["split"],
            weak=float(weak.mean()),search=float(alt.mean()),weak_se=float(weak.std(ddof=1)/len(weak)**.5),
            search_se=float(alt.std(ddof=1)/len(alt)**.5),change_se=float((alt-weak).std(ddof=1)/len(alt)**.5),
            baseline_gain=float((base(24,"search")-base(0,"g2")).mean()),
            plan_continuation_gain=float((base(24,"plan_atk")-base(0,"plan_atk")).mean()),
            win_gain=float((vector(r,"reference",24,"search","win")-vector(r,"reference",0,"g2","win")).mean())))
    return dict(rows=rows,strict_reversals=sum(x["weak"]*x["search"]<0 for x in rows),
        changed=sum(x["weak"]!=x["search"] for x in rows),
        baseline=interval([(x["family"],x["baseline_gain"]) for x in rows]),
        wins=interval([(x["family"],x["win_gain"]) for x in rows]))


def strata(core,matched):
    primary=[r for r in core if r["split"]=="confirm" and r["stop"]=="complete"]
    alternative=[r for r in matched if r["stop"]=="complete"]
    keys={(r["id"],r["counter"]) for r in alternative}
    subset=[r for r in primary if (r["id"],r["counter"]) in keys]
    actual=assess(subset,0)["rows"]
    control={(v["id"],v["counter"],v["unit"]):v for v in assess(alternative,0)["rows"]}
    effects={}
    for unit in ("single","plan"):
        rows=[v for v in actual if v["unit"]==unit]
        effects[unit]=interval([(v["family"],v["gain"]-control[v["id"],v["counter"],unit]["gain"]) for v in rows])
    groups={}
    for r in primary:
        h=r["h"]
        incoming=sum(sum(e["attack_hits"]) for e in h["enemies"])-h["block"]
        tags=["high_pressure" if incoming>=h["hp"]/2 else "lower_pressure",
              "lethal_witness" if r["endpoints"][0]["kind"]=="victory" else "no_lethal_witness",
              "counter_"+str(r["counter"])]
        for tag in tags:
            groups.setdefault(tag,[]).append(r)
    return dict(matched_stops=Counter(r["stop"] for r in matched),paired_gain=effects,
                matched=assess(alternative,0)["summary"],conditional={s:assess(rs,0)["summary"] for s,rs in groups.items()})


def learning(rs,fit):
    confirm=[r for r in rs if r["split"]=="confirm" and r["stop"]=="complete"]
    labels={}
    for r in confirm:
        ys=outcomes(r)
        if ys is None:
            continue
        mats={b:np.array([[y["utility"] for y in w] for w in ws]) for b,ws in ys.items()}
        labels[r["id"],r["counter"]]=mats
    results={}
    for name,stats in fit["results"].items():
        rows=stats["groups"]
        groups={(v["id"],v["counter"]):v for v in rows}
        gain=[]
        regret=[]
        shifts=[]
        for (i,n),g in groups.items():
            mats=labels[i,n]
            best=int(mats["selection"].mean(0).argmax())
            val=mats["reference"].mean(0)
            gain.append((i,float(val[g["chosen"]]-val[g["g2"]])))
            regret.append((i,float(val[best]-val[g["chosen"]])))
            if n!=9:
                continue
            other=groups[i,0]
            predicted=np.array(g["pred"])-other["pred"]
            actual=val-labels[i,0]["reference"].mean(0)
            for a,b in combinations(range(len(val)),2):
                shifts.append(dict(id=i,a=a,b=b,estimated=float(predicted[a]-predicted[b]),observed=float(actual[a]-actual[b])))
        results[name]=dict(gain=interval(gain),independent_regret=interval(regret),shifts=shifts,
            shift_mae=interval([(s["id"],abs(s["estimated"]-s["observed"])) for s in shifts]),
            shift_nonzero=sum(s["observed"]!=0 for s in shifts),shift_correct=sum(s["observed"]*s["estimated"]>0 for s in shifts))
    return results


def paired_noise(rs):
    paired=[]
    independent=[]
    for r in rs:
        if r["split"]!="train" or r["stop"]!="complete":
            continue
        blocks=outcomes(r)
        if blocks is None:
            continue
        ys=np.array([[y["utility"] for y in w] for w in blocks["selection"]+blocks["reference"]])
        var=ys.var(axis=0,ddof=1)
        for i,j in combinations(range(ys.shape[1]),2):
            paired.append(float((ys[:,i]-ys[:,j]).var(ddof=1)/len(ys)))
            independent.append(float((var[i]+var[j])/len(ys)))
    return dict(pairs=len(paired),paired_mean_variance=float(np.mean(paired)),
        independent_mean_variance=float(np.mean(independent)),lower=sum(a<b-1e-9 for a,b in zip(paired,independent)),
        higher=sum(a>b+1e-9 for a,b in zip(paired,independent)))


def battle():
    arms={}
    status=Counter()
    for p in sorted(LOGS.glob("n4b-battle-*/*.json.gz")):
        r=read(p)
        for w in r["worlds"]:
            for arm,y in w["outcomes"].items():
                status[y["status"]]+=1
                if y["utility"] is None:
                    continue
                key=r["id"],r["counter"],w["seed"]
                arms.setdefault((r["domain"],arm),{})[key]=dict(win=int(y["status"]=="predicted_win"),
                    net=r["initial_hp"]-y["terminal"]["hp"],util=y["utility"],seconds=y["seconds"],
                    severe=int(r["initial_hp"]-y["terminal"]["hp"]>=r["initial_hp"]/2),
                    counts=y["counts"],admin=len(y["post_terminal_selection"]))
    summary={}
    comparisons={}
    for (domain,arm),by in arms.items():
        vals=list(by.values())
        cs=Counter()
        for v in vals:
            cs.update(v["counts"])
        summary[domain+"."+arm]=dict(n=len(vals),wins=sum(v["win"] for v in vals),severe=sum(v["severe"] for v in vals),
            seconds=sum(v["seconds"] for v in vals),admin=sum(v["admin"] for v in vals),counts=cs)
        other=arms[domain,"G2/"+arm.split("/")[1]]
        if set(by)!=set(other):
            raise ValueError("Unpaired or censored battle set, explicit adjudication required")
        def diff(k):
            return interval([(i[0],by[i][k]-other[i][k]) for i in by])
        joint=[(i[0],by[i]["net"]-other[i]["net"]) for i in by if by[i]["win"] and other[i]["win"]]
        comparisons[domain+"."+arm]=dict(win=diff("win"),severe=diff("severe"),utility=diff("util"),joint_wins=len(joint),
            joint_net=interval(joint),changes=Counter(f'{other[i]["win"]}->{by[i]["win"]}' for i in by))
    return dict(arms=summary,comparisons=comparisons,status=status)


def main(out):
    t=perf_counter()
    core=records()
    natural=[read(p) for p in sorted((LOGS/"n4b-natural-final").glob("*.gz"))]
    assert len(core)==196 and len(natural)==40
    rs=core+natural
    teachers=report(rs)
    fit=read(LOGS/"n4b-finalfit/result.json")
    zeros=read(LOGS/"n4b-zeros/zeros.json.gz")
    z=[w for p in zeros["train"] for w in p["worlds"]]
    out.mkdir(parents=True,exist_ok=False)
    write(out/"teacher.json.gz",teachers)
    res=dict(coverage={s:Counter(r["stop"] for r in rs if r["split"]==s) for s in ("train","dev","confirm","natural")},
        zeros={k:sum(bool(w[k]) for w in z) for k in ("both_dead","public_join","swapped_two","terminal_resource_diff","turn_diff")},
        teacher={s:{b:v["summary"] for b,v in bs.items()} for s,bs in teachers.items()},unit_gain=compare_units(rs),
        continuation=continuation(core),learning=learning(rs,fit),paired_noise=paired_noise(core),battles=battle(),
        strata=strata(core,[read(p) for p in sorted((LOGS/"n4b-matched").glob("*.gz"))]),analysis_seconds=perf_counter()-t)
    write(out/"results.json.gz",res)


if __name__=="__main__":
    main(Path(sys.argv[1]))
