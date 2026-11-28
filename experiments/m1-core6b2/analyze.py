"""Paired whole-battle analysis, historical coverage and the worker ledger."""
import gzip,json,sys,time
from collections import Counter
from statistics import mean
from branch import H,E,W
from common6 import read,save,sha
from results6 import paired

def gz(name):
    return json.load(gzip.open(E/name))

def regression():
    data=gz("regression.gz")
    summary={};per_root={}
    for key,row in data["roots"].items():
        arms=row["arms"];baseline=arms["low"]
        group=per_root[key]={}
        for arm,entry in arms.items():
            options=entry["options"]
            base=baseline["options"][baseline["best"]]
            best=options[entry["best"]]
            def closed(opts):
                return [o for o in opts if o["q"]["value"] is not None]
            laws={o["law_id"] for o in closed(options)}; blaws={o["law_id"] for o in closed(baseline["options"])}
            valid=best["q"]["value"] is not None
            delta=best["q"]["value"]-base["q"]["value"] if valid else None
            stats=dict(roots=1,closed_reference=int(valid),options=len(options)-1,complete=len(closed(options[1:])),
                    closed_programs=len({o["program"] for o in closed(options)}),closed_laws=len(laws),
                    added_laws=len(laws-blaws),lost_laws=len(blaws-laws),changed=int(valid and best["program"]!=base["program"]),
                    materially_improved=int(valid and delta>.001),gain=delta or 0.,seconds=entry["seconds"],
                    unresolved_mass=sum(sum(o["q"]["gaps"].values()) for o in options[1:]),
                    rule_steps=sum(o["q"]["steps"] for o in options)+entry["extra"].get("duplicate_steps",0),
                    attempted_graphs=len(options)+entry["extra"].get("duplicate_closed_graphs",0),
                    g2_rows=entry["model_work"]["g2_rows"],v2_batches=entry["model_work"]["v2_batches"],
                    v2_rows=entry["model_work"]["v2_rows"])
            summary.setdefault(arm,Counter()).update(stats)
            group[arm]=dict(best=best["q"],delta=delta,added_laws=stats["added_laws"],
                            distinct_laws=len(laws),different_program=bool(stats["changed"]))
    return dict(totals=summary,roots=per_root,seconds=data["seconds"])

def summarize(stage,arm):
    parts=[read(p) for p in sorted(E.glob(f"{stage}-{arm}-*.json"))]
    rows=[r for part in parts for r in part["rows"]]
    ok=[r for r in rows if r["end"] is not None]
    seconds=sum(r["process_seconds"] for r in parts)
    stats=dict(attempts=len(rows),complete=len(ok),wins=sum(r["status"]=="Victory" for r in rows),
               severe=sum(r["status"]=="Defeat" or r["opening"]-r["end"]>=r["opening"]/2 for r in ok),
               loss=mean(r["opening"]-r["end"] for r in ok),failures=Counter(r["reason"] for r in rows if r["end"] is None),
               cost=seconds/len(rows),seconds=seconds,throughput=len(ok)*60/seconds,
               branch_wins=sum(sum(r["branch_winners"].values()) for r in rows),
               eligible_C=sum(r["C"] for r in ok))
    for key in ("queries","closed","candidates","complete_options","reference_steps","option_steps","interventions","realized","changed_first"):
        stats[key]=sum(r[key] for r in rows)
    stats["model_work"]=sum((Counter(r["model_work"]) for r in parts),Counter())
    stats["branch_work"]=sum((Counter(r["metrics"]) for r in parts),Counter())
    stats["rule_steps"]=stats["reference_steps"]+stats["option_steps"]+stats["branch_work"]["duplicate_steps"]
    return rows,stats

def main():
    tick=time.perf_counter()
    selection=read(E/"selection.json");challenger=selection["challenger"];match=selection["matched"]
    reg=regression();data={};comparisons={}
    for stage,arms in [("dev",["v2","low","expand","target","general"]),("confirm",selection["arms"])]:
        data[stage]={};panel={}
        for a in arms:
            panel[a],data[stage][a]=summarize(stage,a)
            if stage=="confirm":
                assert [(r["family"],r["seed"]) for r in panel[a]]==[(r["family"],r["spec"]["seed"]) for r in gz("confirm.gz")]
        comparisons[stage]={f"{a}-{b}":paired(panel[a],panel[b]) for a in arms for b in arms if a!=b}
        inds=[i for i in range(len(panel["low"])) if all(rs[i]["end"] is not None for rs in panel.values())]
        comparisons[stage]["common_all"]={a:paired([rs[i] for i in inds],[panel["low"][i] for i in inds]) for a,rs in panel.items()}
    full=data["confirm"];delta=comparisons["confirm"][challenger+"-"+match]
    ratio=full[challenger]["cost"]/full[match]["cost"]
    gate=dict(cost_ratio=ratio,utility_lower=delta["utility"]["ci"][0],wins_delta=full[challenger]["wins"]-full[match]["wins"],
              complete_delta=full[challenger]["complete"]-full[match]["complete"])
    gate["passed"]=gate["utility_lower"]>0 and ratio<=1.1 and min(gate["wins_delta"],gate["complete_delta"])>=0
    save(E/"results.json",dict(regression=reg,stats=data,comparisons=comparisons,gate=gate))
    from curve import draw
    draw(full,comparisons["confirm"],E/"ability-cost.png")
    analysis_seconds=time.perf_counter()-tick
    from audit6b2 import audit
    audit()
    timings=dict(regression=reg["seconds"],pilot=gz("pilot.gz")["seconds"],b2_replay=gz("b2-paired.gz")["seconds"],
                 dev=sum(z["seconds"] for z in data["dev"].values()),confirm=sum(z["seconds"] for z in full.values()),
                 panel=read(E/"panel-audit.json")["seconds"],analysis=analysis_seconds,
                 conditional_check=gz("conditional-check.gz")["seconds"],audit=read(E/"audit.json")["seconds"])
    save(E/"ledger.json",dict(worker_seconds=timings,measured=sum(timings.values()),ancillary_allowance=180,
          total_upper=sum(timings.values())+180,wall_confirm=read(E/"schedule.json")["wall_seconds"]))
if __name__=="__main__":main()
