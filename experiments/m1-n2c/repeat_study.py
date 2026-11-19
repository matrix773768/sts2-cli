"""Repeat N2B with independent optimizer seeds and frozen attribution controls."""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
from pathlib import Path
import random
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2b"))
import train as n2b
from analyze import read

BASE = HERE.parent / "m1-n2a2"
BASELINE = HERE.parent / "m1-n2b"
PROTOCOL = read(HERE/"protocol.json")


def make_report(items):
    for item in items:
        case = item["case"]
        if case["cohort"] != "report":
            continue
        for arm in PROTOCOL["report_arms"]:
            new = deepcopy(item)
            result = new["case"]
            spec = result["spec"]
            key = n2b.stamp([PROTOCOL["report_domain"], case["id"], arm])
            spec["seed"] = key[:12].upper()
            if arm == "deck_variant":
                card = f'STRIKE_{spec["character"].upper()}'
                index = next(i for i, c in enumerate(spec["deck"]) if c["id"] == card and c["upgrade"] == 0)
                spec["deck"][index] = dict(id=PROTOCOL["variant"]["add"][spec["character"]], upgrade=0)
            result.update(id=key[:16], spec_sha256=n2b.stamp(spec), cohort="new_report",
                          source_id=case["id"], arm=arm)
            yield new


def zero_models():
    mu = n2b.CONFIG["initial_mean"]
    sd = [n2b.CONFIG["initial_sd"]] * len(mu)
    rng = random.Random(PROTOCOL["untrained_seed"])
    models = [dict(id="initial-mean", weights=mu)]
    for i in range(PROTOCOL["untrained_draws"]):
        z = [rng.gauss(0,1) for _ in mu]
        models.append(dict(id=f"untrained-{i+1}", weights=n2b.sample(z,mu,sd)))
    return models


def optimize(output, state, plan, expected, versions):
    mu0 = n2b.CONFIG["initial_mean"]
    sd0 = [n2b.CONFIG["initial_sd"]] * len(mu0)
    rngs = {key:random.Random(seed) for key,seed in PROTOCOL["optimizer_seeds"].items()}
    distributions = {key:(mu0,sd0) for key in rngs}
    champions = []
    schedule = n2b.schedule(plan["cases"])
    state["schedule"] = [[i["case"]["id"] for i in items] for items in schedule]
    for generation, items in enumerate(schedule, 1):
        started = perf_counter()
        models = []
        for key, rng in rngs.items():
            draws = [[rng.gauss(0,1) for _ in mu0] for _ in range(n2b.CONFIG["candidates"])]
            for method, is_random in n2b.FROZEN:
                dist = (mu0,sd0) if is_random else distributions[key]
                models.extend(dict(id=f"{key}-{method}-{generation}-{i}", method=method,
                                   repeat=key, weights=n2b.sample(draw,*dist))
                              for i,draw in enumerate(draws,1))
        sampling_ms = n2b.base.ms(started)
        run = n2b.evaluate(output,items,models,f"generation-{generation}",state,expected,versions)
        started = perf_counter()
        update = dict(generation=generation,repeats={})
        for key in rngs:
            ordering = {}
            for method,_ in n2b.FROZEN:
                subset = [m for m in models if m["repeat"]==key and m["method"]==method]
                ordering[method] = sorted(subset,key=lambda m:n2b.rank(run["scores"][m["id"]]),reverse=True)
                champions.append(ordering[method][0])
            elite = ordering["cem"][:n2b.CONFIG["elite"]]
            if any(run["scores"][m["id"]]["missing"] for m in elite):
                raise ValueError("Too few complete elites")
            previous = distributions[key]
            distributions[key] = n2b.update([m["weights"] for m in elite],*previous)
            update["repeats"][key] = dict(previous=previous,next=distributions[key],
                                          elite=[m["id"] for m in elite],
                                          champions={k:v[0]["id"] for k,v in ordering.items()})
        update["optimizer_ms"] = sampling_ms+n2b.base.ms(started)
        state["updates"].append(update)
        n2b.snapshot(output,state)
    return champions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    plan = read(BASE/"manifest.json")
    prior = read(BASE/"benchmark.json.gz")
    frozen_lock = read(BASELINE/"models.json")
    old_digest = frozen_lock.pop("sha256")
    if n2b.stamp(frozen_lock) != old_digest:
        raise ValueError("Original model lock differs")
    base = n2b.base
    versions = base.s3a.solver_binding(output,base.s3a.FIXED,base.ROOT/"logs/m1-e3f/release")
    for key in ("solver_sha256","game_sha256","headless_sha256"):
        if versions[key] != prior["versions"][key]:
            raise ValueError(f"Environment differs for {key}")
    if prior["manifest_sha256"] != n2b.stamp(plan):
        raise ValueError("Cohort manifest differs")
    expected = {r["id"]:r["root_sha256"] for batch in prior["batches"] for r in batch["roots"]}
    base.Episode = n2b.BudgetEpisode
    zero = zero_models()
    state = dict(protocol=PROTOCOL,inherited=n2b.CONFIG,versions=versions,zero_models=zero,
                 sources={str(p.relative_to(base.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (HERE/"protocol.json", HERE/"repeat_study.py", BASELINE/"policy.py",
                                    BASELINE/"train.py", BASELINE/"protocol.json")},
                 features=n2b.FEATURES, manifest_sha256=n2b.stamp(plan),passes=[],updates=[])
    n2b.snapshot(output,state)
    started = perf_counter()
    champions = optimize(output,state,plan,expected,versions)

    def cohort(name):
        return [i for i in plan["cases"] if i["case"]["cohort"] == name]

    selection = n2b.evaluate(output,cohort("selection"),champions+zero,"selection",state,expected,versions)
    selected = [max((m for m in champions if m["repeat"]==key and m["method"]==method),
                    key=lambda m:n2b.rank(selection["scores"][m["id"]]))
                for key in PROTOCOL["optimizer_seeds"] for method,_ in n2b.FROZEN]
    locked = dict(models=frozen_lock["models"]+zero+selected,
                  old_sha256=old_digest, source_sha256=state["sources"],
                  prior_manifest_sha256=state["manifest_sha256"])
    state["locked_sha256"] = n2b.stamp(locked)
    base.bank.atomic(output/"models.json", locked|{"sha256":state["locked_sha256"]})
    report = dict(domain=PROTOCOL["report_domain"], locked_sha256=state["locked_sha256"],
                  cases=list(make_report(plan["cases"])))
    base.bank.atomic(output/"manifest.json",report)
    state["new_manifest_sha256"] = n2b.stamp(report)

    n2b.evaluate(output,cohort("train"),zero,"zero-train",state,expected,versions)
    n2b.evaluate(output,cohort("report"),zero+selected,"historical-report",state,expected,versions)
    n2b.evaluate(output,report["cases"],locked["models"],"report",state,defaultdict(lambda:None),versions)
    state["elapsed_ms"] = base.ms(started)
    n2b.snapshot(output,state)


if __name__ == "__main__":
    main()
