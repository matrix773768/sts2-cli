"""Frozen 2×2 development study, reusing the qualified public policy runner."""
import argparse
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2c"))
from repeat_study import n2b, read

BASE = HERE.parent / "m1-n2a2"
PROTOCOL = read(HERE/"protocol.json")


def manifest():
    plan = read(BASE/"manifest.json")
    frozen = read(HERE.parent/"m1-n2c/models.json")
    digest = frozen.pop("sha256")
    if n2b.stamp(frozen) != digest:
        raise ValueError("Historical lock changed")
    models = {m["id"]:m for m in frozen["models"]}
    templates = ("strength","barrier","shiv","dexterity")
    out = []
    for item in plan["cases"]:
        c = item["case"]
        if c["cohort"] != "report" or c["complexity"] not in PROTOCOL["pressures"]:
            continue
        encounter = PROTOCOL["encounters"].index(c["spec"]["encounter"])
        pressure = PROTOCOL["pressures"].index(c["complexity"])
        split = "report" if (encounter+templates.index(c["template"])+pressure)%2 else "diagnosis"
        for seed_index in range(2):
            seed = n2b.stamp([PROTOCOL["domain"],c["id"],seed_index])[:12].upper()
            for deck_index in range(2):
                case = deepcopy(item)
                entry = case["case"]
                spec = entry["spec"]
                spec["seed"] = seed
                if deck_index:
                    index = next(i for i,card in enumerate(spec["deck"])
                                 if card["id"].startswith("STRIKE_") and not card["upgrade"])
                    spec["deck"][index] = dict(id=PROTOCOL["replacement"][spec["character"]],upgrade=0)
                id_ = n2b.stamp([PROTOCOL["domain"],c["id"],seed_index,deck_index])[:16]
                entry.update(id=id_,source_id=c["id"],seed_index=seed_index,deck_index=deck_index,
                             diagnostic_split=split,spec_sha256=n2b.stamp(spec))
                out.append(case)
    return dict(protocol=PROTOCOL, prior_lock=digest,cases=out, models=[models[k] for k in PROTOCOL["models"]])


def root_audit(surface):
    snapshot = surface["native"]
    return dict(rng={k:{name:n2b.stamp(state) for name,state in snapshot[k]["rngs"].items()}
                     for k in ("run_rng","player_rng")},
                hand=[c["id"] for c in surface["public_root"]["hand"]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    plan = manifest()
    n2b.base.bank.atomic(output/"manifest.json",plan)
    prior = read(BASE/"benchmark.json.gz")
    base = n2b.base
    versions = base.s3a.solver_binding(output,base.s3a.FIXED,base.ROOT/"logs/m1-e3f/release")
    for key in ("solver_sha256","game_sha256","headless_sha256"):
        if prior["versions"][key] != versions[key]:
            raise ValueError(f"Identity differs for {key}")
    base.Episode = n2b.BudgetEpisode
    state = dict(manifest_sha256=n2b.stamp(plan),versions=versions,lifecycle=[],rows=[],root_audits={},
                 sources={name:sha256(path.read_bytes()).hexdigest() for name,path in
                          (("run",Path(__file__)),("policy",n2b.HERE/"policy.py"),("protocol",HERE/"protocol.json"))})
    start = perf_counter()
    for item in plan["cases"]:
        root = item["case"]["id"]
        try:
            with base.worker(output,item,versions,state["lifecycle"]) as (game,surface):
                state["root_audits"][root] = root_audit(surface)
                game.n2a2_cap = PROTOCOL["budget"]
                for model in plan["models"]:
                    weights = model.get("weights")
                    base.choose = n2b.interaction.choose if weights is None else (
                        lambda obs,actions,_,w=weights: n2b.decide(obs,actions,w))
                    row = base.execute(game,item,False,"factorial")
                    state["rows"].append(row|{"model":model["id"],"evidence":"prediction_only"})
        except base.bank.f1.i2.StopRun as error:
            state["execution_error"] = {"id":root,"reason":str(error)}
            n2b.snapshot(output,state)
            raise
        n2b.snapshot(output,state)
        if len(state["rows"]) % 32 == 0:
            print(len(state["rows"]),flush=True)
    state["elapsed_ms"] = base.ms(start)
    n2b.snapshot(output,state)


if __name__ == "__main__":
    main()
