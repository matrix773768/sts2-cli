"""Public-only feature and trajectory diagnostics, never invoked by policy or engine."""
import argparse
from collections import defaultdict
from dataclasses import asdict, replace
from itertools import combinations
import json
from math import fsum
from pathlib import Path

from run_factorial import HERE, n2b, read
from interaction import Observation
from policy import features, GROWTH

UNQUALIFIED = {"IRON_WAVE","DAGGER_SPRAY","LEG_SWEEP","BACKFLIP","PREDATOR","CLOAK_AND_DAGGER"}


def vector(obs, action):
    return features(obs,action,sum(sum(e.attack_hits) for e in obs.enemies))


def score(v, model):
    return fsum(x*y for x,y in zip(v,model["weights"],strict=True))


def describe(obs,action,models):
    v = vector(obs,action)
    return dict(action=action.native(),card=obs.hand[action.card].id if action.card is not None else None,
                preview=asdict(action.preview) if action.preview else None,
                choice=asdict(action.choice) if action.choice else None, features=v,
                scores={m["id"]:score(v,m) for m in models if "weights" in m})


def observe_trace(row):
    for i,step in enumerate(row["trajectory"]):
        obs = Observation.decode(step["observation"])
        chosen = next(a for a in obs.actions if a.native()==step["action"])
        yield i+1,obs,chosen


def outcomes(rows):
    return {r["model"]:dict(status=r["terminal"]["status"],actions=r["terminal"].get("actions"),
                            terminal=r["terminal"].get("feedback",{}).get("combat_terminal")) for r in rows}


def change_context(name,obs,a,b):
    if name=="phase":
        return replace(obs,turn=obs.turn+6)
    if name=="hp_risk":
        return replace(obs,hp=1 if obs.hp>1 else 40)
    if name=="draw_energy":
        return replace(obs,energy=obs.energy+2)
    if name=="nonlethal_target_threat":
        enemies=list(obs.enemies)
        e0,e1=enemies[a.target],enemies[b.target]
        enemies[a.target]=replace(e0,attack_hits=e1.attack_hits)
        enemies[b.target]=replace(e1,attack_hits=e0.attack_hits)
        return replace(obs,enemies=tuple(enemies))
    raise ValueError(name)


def family_examples(rows,models):
    found = {}
    for row in rows:
        for step,obs,chosen in observe_trace(row):
            damage = [a for a in obs.actions if vector(obs,a)[1]>0]
            probes = {}
            if damage:
                b = damage[0]
                growth = next((a for a in obs.actions if a.card is not None and obs.hand[a.card].id in GROWTH),None)
                defense = next((a for a in obs.actions if vector(obs,a)[4]>0),None)
                draw = next((a for a in obs.actions if vector(obs,a)[5]>0 and a.card!=b.card),None)
                probes = {"phase":(growth,b),"hp_risk":(defense,b),"draw_energy":(draw,b)}
                if len(obs.enemies)>1 and "nonlethal_target_threat" not in found:
                    for x,y in combinations(damage,2):
                        if (x.card==y.card and x.target!=y.target and not vector(obs,x)[2] and not vector(obs,y)[2]
                            and sum(obs.enemies[x.target].attack_hits)!=sum(obs.enemies[y.target].attack_hits)):
                            probes["nonlethal_target_threat"]=(x,y)
                            break
            for name,(a,b) in probes.items():
                if a is None or name in found:
                    continue
                altered = change_context(name,obs,a,b)
                if vector(obs,a)!=vector(altered,a) or vector(obs,b)!=vector(altered,b):
                    raise ValueError("Expected identical scores after public-only fixture change")
                found[name] = dict(id=row["id"],step=step,model=row["model"],observed=asdict(obs),
                                   chosen=chosen.native(),pair=[describe(obs,x,models) for x in (a,b)],
                                   changed={k:v for k,v in asdict(altered).items() if asdict(obs)[k]!=v},
                                   outcome=outcomes([row]))
            if "discard_collision" not in found:
                options=[a for a in obs.actions if a.choice]
                for a,b in combinations(options,2):
                    if a.card==b.card and a.choice.id!=b.choice.id and vector(obs,a)==vector(obs,b):
                        found["discard_collision"]=dict(id=row["id"],step=step,model=row["model"],observed=asdict(obs),
                            chosen=chosen.native(),pair=[describe(obs,x,models) for x in (a,b)],outcome=outcomes([row]))
                        break
            if "lethal_vs_guard" not in found and len(obs.enemies)==1 and vector(obs,chosen)[4]>0:
                lethal=next((a for a in damage if vector(obs,a)[2]),None)
                if lethal is not None:
                    found["lethal_vs_guard"]=dict(id=row["id"],step=step,observed=asdict(obs),chosen=chosen.native(),
                        pair=[describe(obs,a,models) for a in (chosen,lethal)],outcome=outcomes([row]))
            if "missing_preview" not in found:
                option=next((a for a in obs.actions if a.card is not None and obs.hand[a.card].id in UNQUALIFIED
                             and not a.preview),None)
                if option:
                    found["missing_preview"]=dict(id=row["id"],step=step,observed=asdict(obs),
                        option=describe(obs,option,models),chosen=chosen.native(),outcome=outcomes([row]))
    return found


def differing_routes(rows,models,other):
    by_root = defaultdict(dict)
    for row in rows:
        by_root[row["id"]][row["model"]]=row
    examples=[]
    for group in by_root.values():
        a,b=group["initial-mean"],group[other]
        stops={r["terminal"]["status"] for r in (a,b)}
        if stops!={"predicted_win","death"}:
            continue
        for x,y in zip(observe_trace(a),observe_trace(b)):
            i,obs,first=x
            _,other_obs,second=y
            if obs!=other_obs:
                raise ValueError("Traces diverged before public action differed")
            if first==second:
                continue
            examples.append(dict(id=a["id"],step=i,observed=asdict(obs),outcomes=outcomes([a,b]),
                                 mean_action=first.native(),other_action=second.native(),
                                 legal_scores=[describe(obs,action,models) for action in obs.actions]))
            break
    return examples


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args=parser.parse_args()
    p=args.directory
    state=read(p/"ledger.json")
    manifest=read(p/"manifest.json")
    diagnostic = {c["case"]["id"] for c in manifest["cases"] if c["case"]["diagnostic_split"]=="diagnosis"}
    rows = [r for r in state["rows"] if r["id"] in diagnostic]
    models=manifest["models"]
    prior=read(HERE.parent/"m1-n2c/ledger.json.gz")["passes"][-1]["rows"]
    out=dict(collision_and_invariance=family_examples(rows,models),
             divergence={m["id"]:differing_routes(rows,models,m["id"])[:4] for m in models[1:]},
             historical=differing_routes(prior,models,"r2-random-4-6")[:2])
    print(json.dumps(out,indent=2))


if __name__=="__main__":
    main()
