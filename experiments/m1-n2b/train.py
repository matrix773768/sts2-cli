"""Budget-matched CEM and random search with disjoint selection and report passes."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import fsum
from pathlib import Path
import random
from statistics import mean, pstdev
import sys
from time import perf_counter, sleep

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2a2"))
from run_cohort import BudgetEpisode, base, interaction, stamp
from policy import FEATURES, decide

CONFIG = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
FROZEN = (("cem", 0), ("random", 1))
NORMAL = ("predicted_win", "death")


def schedule(cases):
    groups = defaultdict(list)
    for item in cases:
        if item["case"]["cohort"] == "train":
            groups[item["case"]["spec"]["encounter"]].append(item)
    rng = random.Random(CONFIG["schedule_seed"])
    for group in groups.values():
        rng.shuffle(group)
    width = CONFIG["roots_per_encounter"]
    return [[item for key in sorted(groups) for item in groups[key][g*width:(g+1)*width]]
            for g in range(CONFIG["generations"])]


def scores(rows):
    stops = Counter(row["terminal"]["status"] for row in rows)
    won = [r["terminal"]["feedback"]["combat_terminal"] for r in rows if r["terminal"]["status"] == "predicted_win"]
    return dict(n=len(rows), missing=len(rows)-sum(stops[x] for x in NORMAL), wins=len(won),
                hp_sum=fsum(x["hp"]/x["max_hp"] for x in won), stops=dict(stops))


def rank(score):
    return -score["missing"], score["wins"], score["hp_sum"]


def sample(z, mu, sd):
    lo, hi = CONFIG["bounds"]
    return [min(hi, max(lo, m+s*x)) for x,m,s in zip(z,mu,sd,strict=True)]


def update(elite, mu, sd):
    blend = CONFIG["blend"]
    columns = list(zip(*elite, strict=True))
    return ([blend*mean(c)+(1-blend)*m for c,m in zip(columns,mu,strict=True)],
            [max(CONFIG["sd_floor"], blend*pstdev(c)+(1-blend)*s) for c,s in zip(columns,sd,strict=True)])


def snapshot(output, state):
    # A concurrent Windows reader may briefly hold the destination open.
    for attempt in range(5):
        try:
            base.bank.atomic(output / "ledger.json", state)
        except PermissionError:
            if attempt == 4:
                raise
            sleep(.05 * (attempt + 1))
        else:
            return


def evaluate(output, items, models, phase, state, expected_roots, versions):
    began = perf_counter()
    data = dict(phase=phase, models=models, rows=[], lifecycle=[])
    state["passes"].append(data)
    game_error = base.bank.f1.i2.StopRun
    for item in items:
        id_ = item["case"]["id"]
        with base.worker(output, item | {"root_sha256": expected_roots[id_]}, versions,
                         data["lifecycle"]) as (game, _):
            game.n2a2_cap = CONFIG["budget"]
            for model in models:
                weights = model.get("weights")
                base.choose = interaction.choose if weights is None else (
                    lambda obs, actions, _, w=weights: decide(obs, actions, w))
                try:
                    row = base.execute(game, item, model.get("defense_first", False), phase)
                except game_error as error:
                    data["rows"].append(dict(model=model["id"], id=id_,
                                             terminal=dict(status="execution_error", detail=str(error))))
                    snapshot(output, state)
                    raise
                if row["terminal"]["status"] not in (*NORMAL, "unsupported", "truncated"):
                    data["rows"].append(row | {"model": model["id"]})
                    snapshot(output, state)
                    raise ValueError("Unexpected environment stop")
                if phase != "report":
                    row["terminal"].pop("audit_actions", None)
                    row["terminal"].pop("audit_stamps", None)
                    row.pop("trajectory")
                data["rows"].append(row | {"model": model["id"], "evidence": "prediction_only"})
        snapshot(output, state)
        missing = sum(r["terminal"]["status"] not in NORMAL for r in data["rows"])
        if missing / len(data["rows"]) >= CONFIG["missing_abort_fraction"] and len(data["rows"]) >= 24:
            raise ValueError(f"Missing-feedback stop in {phase}: {missing}/{len(data['rows'])}")
    data["scores"] = {m["id"]: scores([r for r in data["rows"] if r["model"] == m["id"]]) for m in models}
    data["wall_ms"] = base.ms(began)
    snapshot(output, state)
    print(phase, len(data["rows"]), round(data["wall_ms"]), flush=True)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    root = HERE.parent / "m1-n2a2"
    from analyze import read
    plan = read(root / "manifest.json")
    prior = read(root / "benchmark.json.gz")
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    for key in ("solver_sha256", "game_sha256", "headless_sha256"):
        if versions[key] != prior["versions"][key]:
            raise ValueError(f"Environment identity differs for {key}")
    if prior["manifest_sha256"] != stamp(plan):
        raise ValueError("Manifest does not match qualification")
    expected = {r["id"]: r["root_sha256"] for b in prior["batches"] for r in b["roots"]}
    base.Episode = BudgetEpisode
    rng = random.Random(CONFIG["sampling_seed"])
    mu = CONFIG["initial_mean"]
    sd = [CONFIG["initial_sd"]] * len(mu)
    initial = mu, sd
    batches = schedule(plan["cases"])
    state = dict(protocol=CONFIG, features=FEATURES, versions=versions, manifest_sha256=stamp(plan),
                 sources={p: sha256((HERE/p).read_bytes()).hexdigest() for p in
                          ("policy.py","train.py","protocol.json")},
                 schedule=[[item["case"]["id"] for item in batch] for batch in batches], passes=[], updates=[])
    snapshot(output, state)
    experiment = perf_counter()
    champions = []
    for generation, items in enumerate(batches):
        started = perf_counter()
        z = [[rng.gauss(0,1) for _ in FEATURES] for _ in range(CONFIG["candidates"])]
        models = [dict(id=f"{method}-{generation+1}-{i+1}", method=method,
                       weights=sample(draw, *(initial if index else (mu,sd))))
                  for method,index in FROZEN for i,draw in enumerate(z)]
        sample_ms = base.ms(started)
        result = evaluate(output, items, models, f"generation-{generation+1}", state, expected, versions)
        started = perf_counter()
        ranked = {}
        for method,_ in FROZEN:
            by_method = [m for m in models if m["method"] == method]
            ranked[method] = sorted(by_method, key=lambda m: rank(result["scores"][m["id"]]), reverse=True)
            champions.append(ranked[method][0])
        elite = ranked["cem"][:CONFIG["elite"]]
        if any(result["scores"][model["id"]]["missing"] for model in elite):
            raise ValueError("Too few fully evaluated CEM elites")
        new_mu,new_sd = update([m["weights"] for m in elite],mu,sd)
        state["updates"].append(dict(mean=mu, sd=sd, next_mean=new_mu, next_sd=new_sd,
                                     elite=[m["id"] for m in elite],
                                     champions={k:v[0]["id"] for k,v in ranked.items()},
                                     optimizer_ms=sample_ms+base.ms(started)))
        mu,sd = new_mu,new_sd
        snapshot(output,state)
    fixed = [dict(id="fixed-attack",defense_first=False),dict(id="fixed-defense",defense_first=True)]
    select = evaluate(output,[i for i in plan["cases"] if i["case"]["cohort"]=="selection"],
                      champions+fixed,"selection",state,expected,versions)
    selected = [max((m for m in champions if m["method"]==method),
                    key=lambda m:rank(select["scores"][m["id"]])) for method,_ in FROZEN]
    locked = dict(models=selected+fixed, protocol_sha256=state["sources"]["protocol.json"],
                  policy_sha256=state["sources"]["policy.py"], manifest_sha256=state["manifest_sha256"])
    base.bank.atomic(output/"models.json", locked | {"sha256": stamp(locked)})
    state["locked_model_sha256"] = stamp(locked)
    evaluate(output,[i for i in plan["cases"] if i["case"]["cohort"]=="report"],
             selected+fixed,"report",state,expected,versions)
    state["elapsed_ms"] = base.ms(experiment)
    snapshot(output,state)


if __name__ == "__main__":
    main()
