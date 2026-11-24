"""Bounded public battle and feature stages for INF1."""
import argparse
from collections import Counter, defaultdict
from time import perf_counter
import random

from value import ROOT, Path, load
from dc_common import arms, config, frozen, read, write_json
from dc_roots import BASIC, manifest, world
from fit import progress, stopped
from dc_metrics import ledger, describe
from loop_battle import Host, run as baseline, read_ledger
from sv_data import Encoder, Shards, examples, policy_key
from battle import BatchCounts, run
from tools.training_manager.common import write as write_atomic
from tools.training_manager.ledger import identity as ledger_identity

DC1=ROOT/"logs/m1-dc1-formal"
CFG=config() | {"direct_stop_margin":0.}


def deploy(checkpoint, budget):
    if checkpoint is None:
        return baseline, arms()["D2-search" if budget else "D2"]
    _, saved=load(checkpoint)
    # Historical D2 identity is the common continuation prior. After a
    # generation, select its actual previous direct behavior slot.
    policy=saved.get("deployment",arms()["D2"][1])
    return run,(checkpoint,policy,budget)


def revised(spec, package, catalog):
    if not package:
        return spec
    deck=[dict(c) for c in spec["deck"]]
    card_ids={c["id"] for c in deck}
    synergy={"exhaust-draw":"TRUE_GRIT","draw-energy":"SETUP_STRIKE",
             "block-carry":"IRON_WAVE","hp-strength-multihit":"TWIN_STRIKE",
             "exhaust-energy":"BURNING_PACT","topdeck-repeat":"SETUP_STRIKE",
             "zero-cost-exhaust":"TRUE_GRIT","strength-multihit":"POMMEL_STRIKE"}
    pairs=[("STRIKE_IRONCLAD",synergy.get(package,"POMMEL_STRIKE")),
           ("DEFEND_IRONCLAD","SHRUG_IT_OFF")]
    for old,new in pairs:
        position=next((i for i,c in enumerate(deck) if c["id"]==old),None)
        if position is not None and new not in card_ids and new in catalog:
            deck[position]={"id":new,"upgrade":0}
            card_ids.add(new)
    return spec | {"deck":deck}


def upgraded_families():
    source=read(DC1/"family-analysis.json")
    catalog={c["id"] for c in read(DC1/"roots/catalog.json")["characters"][0]["cards"]}
    existing={tuple(sorted(c["id"] for c in f["spec"]["deck"])) for f in source}
    def nonbasic(spec):
        return Counter(c["id"] for c in spec["deck"] if c["id"] not in BASIC)
    comparison=[(f["split"],nonbasic(f["spec"])) for f in source]
    result=[]
    for f in source:
        spec=revised(f["spec"],f["package"],catalog)
        key=tuple(sorted(c["id"] for c in spec["deck"]))
        deck=nonbasic(spec)
        if spec!=f["spec"] and (key in existing or any(
                other!=f["split"] and sum((deck&cards).values())>.8*sum((deck|cards).values())
                for other,cards in comparison)):
            spec=f["spec"]
        elif spec!=f["spec"]:
            existing.add(key)
            comparison.append((f["split"],deck))
        result.append((f,spec))
    return result


def independent(out):
    for split in ("development","challenge"):
        jobs=[]
        for f,spec in upgraded_families():
            if f["split"]!=split or not f["package"] or spec==f["spec"]:
                continue
            for hp in (80,160,999):
                for repeat in range(2):
                    recipe=world(spec|{"hp":hp,"max_hp":hp},CFG,f["id"],repeat,f"dc2b-{split}-{hp}")
                    jobs.append([len(jobs),recipe,split,f["id"],f["room"]])
        purpose="complex_development" if split=="development" else "confirmation_sealed"
        frozen(out/f"{split}.json",manifest(CFG,purpose,jobs))


def production(out, generation, count, previous, search=False, night=False, namespace="dc2b-night1"):
    by_family=defaultdict(list)
    histories=([out.parent/f"g{i}-direct/ledger" for i in range(1,int(previous.name)+1)]
               if night and previous else [previous] if previous else [])
    for history in histories:
        for entry in read_ledger(history,full=False):
            r=entry["row"]
            by_family[r["family"]].append({k:r[k] for k in ("terminal","length","status")} |
                {"root":{k:r["root"][k] for k in ("hp","max_hp")}})

    candidates=defaultdict(list)
    diagnostic=[]
    for f,spec in upgraded_families():
        if f["split"]!="train" or (f["diagnosis"] in ("currently_unsolved","long_or_incomplete")
                                  and not f["package"]):
            continue
        category=("complex" if f["package"] else "improvable" if f["diagnosis"] in
                  ("search_improvable","policy_disagreement") else "resource" if f["D2"]["win_rate"]==1 else "base")
        high=[r for r in by_family[f["id"]] if r["root"]["max_hp"]==999]
        qualified=sum(r["status"]=="predicted_win" and r["length"]<128 for r in high)
        if category=="complex" and len(high)>=4 and qualified*2<len(high):
            diagnostic.append(f["id"])
            continue
        candidates[category].append((f,spec))
    rng=random.Random(714031+generation)
    schedule=["complex"]*4+["improvable"]*3+["resource"]*2+["base"]
    jobs=[]
    categories=Counter()
    promoted={80:set(),160:set()}
    for i in range(count):
        category="improvable" if search and i%5 else schedule[i%len(schedule)]
        if not candidates[category]:
            raise ValueError(f"No qualified families in {category}")
        categories[category]+=1
        f,spec=rng.choice(candidates[category])
        hp=80
        if category=="complex":
            hp=999
            prior=by_family[f["id"]]
            for level,next_level in ((999,160),(160,80)):
                sample=[r for r in prior if r["root"]["max_hp"]==level]
                wins=[r for r in sample if r["status"]=="predicted_win" and r["length"]<128]
                if len(sample)>=4 and len(wins)/len(sample)>=.875 and sum(
                    r["root"]["hp"]-r["terminal"]["hp"] for r in wins)/len(wins)<=35:
                    hp=next_level
                else:
                    break
            if hp in promoted:
                promoted[hp].add(f["id"])
            if i%5==0:
                hp=999
        hp_now=hp if hp!=80 else min(80,f["spec"]["hp"])
        recipe=world(spec|{"hp":hp_now,"max_hp":hp},CFG,f["id"],i,f"dc2b-{generation}-{out.name}" if not night else f"{namespace}-{generation}-{out.name}")
        split="validation" if int(f["id"][:8],16)%7==0 else "train"
        jobs.append([i,recipe,split,f["id"],f["room"]])
    write_atomic(out/"promotion.json",{str(hp):len(families) for hp,families in promoted.items()})
    return manifest(CFG,"experience_dc2b",jobs) | dict(categories=categories,diagnostic=sorted(diagnostic))


def cache(out, directory, checkpoint):
    out.mkdir(parents=True,exist_ok=True)
    if checkpoint:
        _,saved=load(checkpoint)
    else:
        from sv_model import load as old
        _,saved=old(arms()["D2"][0])
    encoder=Encoder(saved["vocabulary"])
    shards=Shards(out)
    policy=None
    for item in read_ledger(directory):
        row=item["row"]
        if not row["complete"] or row["split"] not in ("train","validation"):
            continue
        if row["purpose"]=="train" and int(row["family"][:8],16)%7==0:
            row["split"]="validation"
        key=policy_key(row["behavior"])
        if policy and key!=policy:
            raise ValueError("Mixed behavior identities")
        policy=key
        shards.add(row["split"],list(examples(row,encoder,dict(hp_bins=32),0,item["ordinal"],12)))
    for split in shards.paths:
        shards.flush(split)
    frozen(out/"manifest.json",dict(policy=policy,shards=shards.paths))


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode",choices=("development","complex-development","produce","cache","gate","freeze"))
    cli.add_argument("output",type=Path)
    cli.add_argument("--checkpoint",type=Path)
    cli.add_argument("--previous",type=Path)
    cli.add_argument("--ledger",type=Path)
    cli.add_argument("--count",type=int,default=16)
    cli.add_argument("--generation",type=int,default=0)
    cli.add_argument("--budget",type=int,default=0)
    cli.add_argument("--chunk",type=int,default=32)
    cli.add_argument("--target",type=int)
    cli.add_argument("--reference",type=Path)
    cli.add_argument("--gate",type=Path)
    cli.add_argument("--night-history",action="store_true")
    cli.add_argument("--night-namespace",default="dc2b-night1")
    a=cli.parse_args()
    if a.gate and read(a.gate)["passed"] is not True:
        return 3
    out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    if a.mode=="freeze":
        independent(out)
        return 0
    if a.mode=="gate":
        from dc_metrics import paired
        base=ledger(a.reference)
        candidate=ledger(a.ledger)
        if base.keys()!=candidate.keys():
            raise ValueError("Development gate cohorts do not match")
        comparison=paired(((base[i],candidate[i]) for i in base),bootstrap=True)
        passed=(comparison["win_delta"]>=-.05 and comparison["death_delta"]<=.05
                and comparison["joint_complete"]>=.98*len(base))
        write_atomic(out/"gate.json",dict(passed=passed,comparison=comparison,
                     evidence={key:ledger_identity(path/"results.sqlite") for key,path in
                               (("reference",a.reference),("candidate",a.ledger))}))
        return 0 if passed else 3
    if a.mode=="cache":
        cache(out,a.ledger,a.checkpoint)
        return 0
    if a.mode in ("development","complex-development"):
        spec=read(a.reference if a.mode=="complex-development" else DC1/"roots/development.json")
        if a.mode=="complex-development" and spec["purpose"]!="complex_development":
            raise ValueError("Only the complex development partition may run automatically")
        spec=spec|{"jobs":spec["jobs"][:a.count]}
    else:
        spec=production(out,a.generation,a.count,a.previous,bool(a.budget),a.night_history,a.night_namespace)
    path=out/"roots.json"
    frozen(path,spec)
    battle,model=deploy(a.checkpoint,a.budget)
    host=Host(out,ROOT/"logs/m1-sv4a-host",CFG)
    compact=BatchCounts() if a.mode=="produce" and a.night_history else None
    options={"compact":compact} if compact else {}
    started=perf_counter()
    done,complete=0,0
    ledger_path=out/"ledger/results.sqlite"
    target=a.target or len(spec["jobs"])
    try:
        if ledger_path.exists():
            result=battle(host,path,out/"ledger",CFG,*model,
                          epsilon=.05 if a.mode=="produce" else 0.,max_new=0,**options)
            if result:
                done=result["attempts"]
                complete=result["complete"]
        initial=complete if a.target else done

        def publish():
            units=complete if a.target else done
            progress(min(units,target),target,ledger_path if done else None,started,new_units=units-initial,
                     attempts=done,attempt_limit=len(spec["jobs"]),complete=complete)

        publish()
        while done<len(spec["jobs"]) and (not a.target or complete<a.target):
            if stopped():
                return 75
            result=battle(host,path,out/"ledger",CFG,*model,
                          epsilon=.05 if a.mode=="produce" else 0.,max_new=min(a.chunk,target-complete) if a.target and a.night_history else a.chunk,**options)
            done=result["attempts"]
            complete=result["complete"]
            publish()
            if compact and (result["status"].get("error",0) or result["counts"].get("terminal_mismatch",0)):
                raise ValueError("Night ledger contains an execution or terminal mismatch")
        if a.mode != "produce":
            rows=list(ledger(out/"ledger").values())
            write_json(out/"metrics.json",{str(hp):describe(r for r in rows if r["root"]["max_hp"]==hp)
                                         for hp in (80,160,999)})
        return 3 if a.target and complete<a.target else 0
    finally:
        host.close()
        if compact:
            compact.close(out/"ledger")


if __name__=="__main__":
    raise SystemExit(main())
