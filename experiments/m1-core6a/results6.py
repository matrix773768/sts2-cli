"""All-attempt outcomes, clustered confidence bounds and full-production cost."""
from collections import Counter
import gzip
from statistics import mean
import time
import numpy as np
from common6 import *
from models import payoff

def summarize(stage,arm):
    files=sorted(E.glob(f"{stage}-{arm}-*.json"))
    receipts=[read(f) for f in files]
    rows=[r for part in receipts for r in part["rows"]]
    ok=[r for r in rows if r["end"] is not None]
    total=lambda k:sum(r[k] for r in rows)
    secs=sum(r["worker"] for r in receipts)
    full_seconds=sum(r.get("process_seconds",r["worker"]) for r in receipts)
    metrics=Counter();work=Counter()
    for r in receipts:
        metrics.update(r["metrics"]);work.update(r["model_work"])
    out=dict(attempts=len(rows),complete=len(ok),wins=sum(r["status"]=="Victory" for r in rows),
             severe=sum(r["status"]=="Defeat" or r["opening"]-r["end"]>=r["opening"]/2 for r in ok),
             mean_loss=mean(r["opening"]-r["end"] for r in ok),failures=Counter(r["reason"] for r in rows if r["end"] is None),
             queries=total("queries"),closed=total("closed"),options=total("candidates"),closed_options=total("complete_options"),
             interventions=total("interventions"),learned_wins=total("learned_wins"),learned_options=total("learned_candidates"),
             completed_query_rule_steps=total("option_steps")+total("reference_steps"),C=sum(r["C"] for r in ok),
             actions=sum(r["steps"] for r in ok),worker_seconds=secs,per_attempt=full_seconds/len(rows),eligible_per_min=60*len(ok)/full_seconds,
             rollout_export_seconds=total("seconds"),validation_seconds=sum(r["validation"] for r in receipts),
             with_imports=full_seconds,bytes=sum(r["bytes"] for r in receipts),
             metrics=metrics,model_work=work)
    return rows,out

def paired(a,b):
    assert len(a)==len(b) and all((r["family"],r["seed"])==(s["family"],s["seed"]) for r,s in zip(a,b))
    fam=list(dict.fromkeys(r["family"] for r in a))
    ix={f:i for i,f in enumerate(fam)}
    # Each bootstrap draw keeps the paired worlds and both sides of each family together.
    cells=np.zeros((len(fam),10))
    bothwin=[]
    swing=Counter()
    def utility(r):
        return -50. if r["status"]=="Defeat" else float(payoff(torch.tensor(r["opening"]-r["end"]),torch.tensor(r["maximum"])))
    for x,y in zip(a,b):
        i=ix[x["family"]]; wx,wy=x["status"]=="Victory",y["status"]=="Victory"
        cx,cy=x["end"] is not None,y["end"] is not None
        row=cells[i]
        row[:3]+=[1,int(wx)-int(wy),int(cx)-int(cy)]
        if cx and cy:
            row[3:5]+=[1,utility(x)-utility(y)]
            swing[int(wx)-int(wy)]+=1
            if wx and wy:bothwin.append(x["opening"]-x["end"]-y["opening"]+y["end"])
        row[5:7]+=[x["seconds"],y["seconds"]]
    rng=np.random.default_rng(6109)
    draws=np.concatenate([cells[rng.integers(len(fam),size=(250,len(fam)))].sum(1) for _ in range(40)])
    def stat(num,den):
        return dict(mean=cells[:,num].sum()/cells[:,den].sum(),ci=np.quantile(draws[:,num]/draws[:,den],[.025,.975]).tolist())
    return dict(common=int(cells[:,3].sum()),families=int(sum(cells[:,3]>0)),utility=stat(4,3),win_delta=stat(1,0),
                completion_delta=stat(2,0),fight_time_ratio=stat(5,6),gained=swing[1],lost=swing[-1],both_win=len(bothwin),
                same_win_loss=mean(bothwin) if bothwin else None)

def main():
    tick=time.perf_counter()
    selection=read(E/"selection.json")
    panel=json.load(gzip.open(E/"confirm.gz"))
    assert len(set(r["family"] for r in panel))==320 and len(set(r["spec"]["seed"] for r in panel))==640
    stats={};comparisons={}
    for stage,arms in [("dev",["g2","v2","direct","low","g2low","same32","trim32","same24","same48","clone"]),("confirm",[*selection["arms"],"clone"])]:
        panels={}
        stats[stage]={}
        comparisons[stage]={}
        for arm in arms:
            rows,s=summarize(stage,arm)
            assert len(rows)==(640 if stage=="confirm" else 64)
            if stage=="confirm":
                assert [(r["family"],r["seed"]) for r in rows]==[(r["family"],r["spec"]["seed"]) for r in panel]
            panels[arm]=rows
            stats[stage][arm]=s
        for arm in arms:
            comparisons[stage][arm+" minus v2"]=paired(panels[arm],panels["v2"])
        for a,b in [("direct","g2"),("direct","clone"),("low","g2low"),("low","direct"),("low","g2")]:
            comparisons[stage][a+" minus "+b]=paired(panels[a],panels[b])
        inds=[i for i in range(len(panels["v2"])) if all(row[i]["end"] is not None for row in panels.values())]
        comparisons[stage]["common_all"]={a:paired([rs[i] for i in inds],[panels["v2"][i] for i in inds]) for a,rs in panels.items()}
    full=stats["confirm"]
    def gate(arm):
        p=comparisons["confirm"][arm+" minus v2"]
        ratio=full[arm]["per_attempt"]/full["v2"]["per_attempt"]
        noninferior=(p["utility"]["ci"][0]>-3 and p["win_delta"]["ci"][0]>-.03 and p["completion_delta"]["ci"][0]>-.03)
        improves=(p["utility"]["ci"][0]>0 and full[arm]["wins"]>=full["v2"]["wins"] and full[arm]["complete"]>=full["v2"]["complete"])
        return dict(cost_ratio=ratio,noninferior=bool(noninferior),fast=bool(noninferior and ratio<=.80),
                    same_cost_improves=bool(improves and ratio<=1.10))
    save(E/"results.json",dict(stats=stats,comparisons=comparisons,
                               gates={a:gate(a) for a in set(["low","same32",selection["matched"]])}))
    cost={}
    for phase in ("dev","cal","confirm"):
        cost[phase]=sum((r.get("process_seconds",r["worker"])) for r in (read(p) for p in E.glob(phase+"-*-*.json")))
    cost["data"]=read(E/"source.json")["seconds"]
    cost["fit"]=sum(read(E/f"fit-{s}.json")["seconds"] for s in (6119,6233))
    cost["teachers"]=read(E/"teacher-check.json")["seconds"]
    cost["portable"]=read(E/"portable.json")["seconds"]
    cost["shared_menu"]=read(E/"shared-menu.json")["seconds"]
    cost["audit"]=read(E/"audit.json")["seconds"]
    cost["analysis"]=time.perf_counter()-tick
    allowance=180
    save(E/"ledger.json",dict(seconds=cost,measured=sum(cost.values()),allowance=allowance,total=sum(cost.values())+allowance,
         allowance_scope="Opening freeze, initial import and evaluation retries, three early development interpreter starts, orchestration and final checks."))
if __name__=="__main__":main()
