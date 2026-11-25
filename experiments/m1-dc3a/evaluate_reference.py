"""Evaluate a frozen public policy against a fixed, native-verified reference library."""
import argparse
import json
import math
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
import random
import sqlite3

import numpy as np

from reference import HERE, ROOT, BUILD, Host, checksum, config, digest, read, write_json
from dc_common import arms
from loop_battle import collect
from loop_policy import NetworkPolicy, BattlePolicy


def database(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        return {key:json.loads(data) for key,data in db.execute("SELECT id,payload FROM results")}


def run(reference, out, arm, checkpoint, audited, search):
    refs=database(reference)
    out.mkdir(parents=True,exist_ok=True)
    cfg=config()|{"workers":1,"direct_stop_margin":0.}
    host=Host(out,BUILD,cfg)
    if checkpoint:
        # DC2B admission is restricted to the released G0 or a matching full-generation audit.
        if checkpoint.resolve()!=ROOT/"logs/inf1/jobs/dc2b-initial/initial/best.pt":
            proof=read(audited)
            if not proof["complete"] or proof["sha256"]!=checksum(checkpoint):
                raise ValueError("Expected an audited, immutable DC2B checkpoint")
        import sys
        sys.path.insert(0,str(HERE.parent/"m1-dc2b"))
        from battle import Policy, Controller
        from value import load
        _, saved=load(checkpoint)
        model=Policy(checkpoint,saved.get("deployment",arms()["D2"][1]),350 if search else 0,0.,host.version,cfg)
        controller=Controller
    else:
        model=NetworkPolicy(*arms()[arm],0.,host.version,cfg)
        controller=BattlePolicy
    identity=digest([checksum(reference),model.definition,checksum(Path(__file__))])
    from dc_common import frozen
    frozen(out/"identity.json",{"sha":identity})
    for key,source in refs.items():
        path=out/f"{key}.json"
        if path.exists():
            continue
        world=source["world"]
        lane=host.lane()
        parent=lane.request
        observations=[]
        def attest(command,**args):
            reply=parent(command,**args)
            if command=="pre0_start":
                public=host.project(reply["episode"]["observation"])
                root=digest([public,parent("synthetic_snapshot"),parent("f1_audit")])
                observations.append(root)
                if root!=source["root"]:
                    raise ValueError("Private root mismatch")
            return reply
        lane.request=attest
        policy=controller(model,host.project,lambda rows:next(model.forward([(rows,)])),random.Random(0))
        job=[0,world["spec"],"development",world["family"],world["room"]]
        record=collect(lane,policy,model.definition,{"config":{"action_cap":256,"version":"dc3a"},"purpose":"evaluation"},
                       job,key)
        host.close()
        row=record["row"]
        if observations!=[source["root"]] or row["status"]=="error":
            raise ValueError(f"Unpaired evaluation {key}: {row['reason']}")
        write_json(path,{k:v for k,v in row.items() if k!="steps"}|{"attested_root":observations[0]})


def utility(hp, maximum, end, death=False):
    if death:
        return -50.
    loss=hp-end
    mixed=10*math.log1p(max(0,loss)/10)+.05*max(0,loss)+min(loss,0)
    weight=1. if maximum>=500 else .5 if maximum>100 else 0.
    return 100-min(149,(1-weight)*loss+weight*mixed)


def statistics(pairs):
    gaps=[(r["world"]["family"],m["root"]["hp"]-m["terminal"]["hp"]-r["reference"]["net"])
          for r,m in pairs if r["reference"] and m["status"]=="predicted_win"]
    valid=[v for _,v in gaps]
    known=sum(bool(r["reference"]) for r,m in pairs)
    counts=Counter(f"{'win' if r['reference'] else 'no_verified_win'}:{m['status']}" for r,m in pairs)
    utilities=[]
    for ref,row in pairs:
        if ref["reference"] and row["status"] in ("death","predicted_win"):
            spec=ref["world"]["spec"]
            context=spec["hp"],spec["max_hp"]
            utilities.append(utility(*context,row["terminal"]["hp"],row["status"]=="death")
                             -utility(*context,ref["reference"]["end_hp"]))
    result=dict(utility_joint_terminal_count=len(utilities),
                utility_model_minus_reference=float(np.mean(utilities)) if utilities else None,n=len(pairs),known=known,coverage=counts["win:predicted_win"]/known if known else None,
                combinations=counts,joint=len(valid))
    if gaps:
        groups=defaultdict(list)
        for family,value in gaps:
            groups[family].append(value)
        rng=np.random.default_rng(314159)
        strata=list(groups.values())
        intervals=[np.mean([v for i in rng.integers(len(strata),size=len(strata)) for v in strata[i]]) for _ in range(1000)]
        result.update(mean=float(np.mean(valid)),quantiles=np.quantile(valid,[.5,.9,.95]).tolist(),
                      at_most={str(k):float(np.mean(np.array(valid)<=k)) for k in (0,5,10)},
                      better=float(np.mean(np.array(valid)<0)),cluster_ci95=np.quantile(intervals,[.025,.975]).tolist())
    return result


def report(reference, names):
    refs=database(reference)
    models={p.name:{k:read(p/f"{k}.json") for k in refs} for p in names}
    for rows in models.values():
        if any(row["attested_root"]!=refs[k]["root"] for k,row in rows.items()):
            raise ValueError("Unpaired rows")
    fixed={k for k,r in refs.items() if r["reference"] and all(m[k]["status"]=="predicted_win" for m in models.values())}
    result={}
    from dc_roots import static
    catalog={c["id"]:c for c in read(ROOT/"logs/m1-dc1-formal/roots/catalog.json")["characters"][0]["cards"]}
    for name,model in models.items():
        strata=defaultdict(list)
        for k,r in refs.items():
            w=r["world"]
            for group in ("all",w["source"],str(w["spec"]["max_hp"]),w["room"],w["spec"]["encounter"]):
                strata[group].append((r,model[k]))
            traits=static(w["spec"]["deck"],catalog)
            for group in [*(f"mechanism:{v}" for v in traits["interactions"]),
                          f"interaction_count:{len(traits['interactions'])}"]:
                strata[group].append((r,model[k]))
            if r["reference"]:
                loss=r["reference"]["net"]
                time=next(v["first_win_rpc_seconds"] for v in r["tiers"]
                          if v.get("validation",{}).get("status")=="native_win")
                strata[f"solver_loss:{'<=10' if loss<=10 else '11-50' if loss<=50 else '>50'}"].append((r,model[k]))
                strata[f"first_search_seconds:{'<=1' if time<=1 else '1-10' if time<=10 else '>10'}"].append((r,model[k]))
        result[name]={"strata":{s:statistics(p) for s,p in strata.items()},
                      "fixed":statistics([(refs[k],model[k]) for k in sorted(fixed)])}
    baseline=result.get("G0-DC",{}).get("fixed",{}).get("mean")
    if baseline is not None and baseline>1:
        for value in result.values():
            value["gap_closed"]=1-value["fixed"]["mean"]/baseline
    return result


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("reference",type=Path)
    cli.add_argument("--output",type=Path)
    cli.add_argument("--arm",choices=("D2","D2-search"),default="D2")
    cli.add_argument("--checkpoint",type=Path)
    cli.add_argument("--audited",type=Path)
    cli.add_argument("--search",action="store_true")
    cli.add_argument("--report",type=Path,nargs="+")
    a=cli.parse_args()
    if a.report:
        write_json(a.output,report(a.reference,a.report))
    else:
        run(a.reference,a.output,a.arm,a.checkpoint,a.audited,a.search)
