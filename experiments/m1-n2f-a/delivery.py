"""Package immutable artifacts and deterministic diagnostics from the locked run."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from statistics import mean, median

from study_design import HERE, FAMILIES, digest, file_hash, read, save
from learning import data
from rollout import NORMAL, rows, text_hash, training_qualification


def archive(path, value):
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))


def evidence(cases, ledger):
    status = defaultdict(Counter)
    slices = defaultdict(Counter)
    pairs = defaultdict(list)
    outcomes = defaultdict(dict)
    exposure = defaultdict(Counter)
    capped = []
    winning_hp = defaultdict(list)
    for row in ledger:
        case = cases[row["id"]]
        key = f'{case["cohort"]}/{case["family"]}'
        encounter = case["spec"]["encounter"]
        outcome = row["terminal"]["status"]
        arm = case["slot_a"], case["slot_b"]
        status[case["cohort"]][outcome] += 1
        if outcome == "predicted_win":
            hp = row["terminal"]["feedback"]["combat_terminal"]["hp"]
            for group in (case["cohort"], key):
                winning_hp[group].append(hp)
        for group in (key, f"{key}/{encounter}", f"{key}/D{arm[0]}{arm[1]}"):
            slices[group][outcome] += 1
        if row.get("root_audit"):
            pairs[case["pair"]].append(row["root_audit"])
        outcomes[key, case["pair"]][arm] = int(outcome == "predicted_win") if outcome in NORMAL else None
        if arm == (1, 1) or outcome == "truncated":
            plays = []
            for step in row["trajectory"]:
                index = step["action"].get("args", {}).get("card_index")
                if index is not None:
                    plays.append(step["observation"]["hand"][index]["id"])
            if arm == (1, 1):
                a, b = FAMILIES[case["family"]][1]
                exposure[f"{key}/{outcome}"].update(n=1, played_a=int(a in plays), played_b=int(b in plays),
                                                    both=int(a in plays and b in plays),
                                                    a_then_b=int(a in plays and b in plays
                                                                 and plays.index(a) < plays.index(b)))
            if outcome == "truncated" and row["trajectory"]:
                last = row["trajectory"][-1]["observation"]
                capped.append(dict(id=row["id"], family=case["family"], encounter=encounter,
                                   hp=last["hp"], turn=last["turn"], enemy_hp=sum(e["hp"] for e in last["enemies"]),
                                   plays=Counter(plays), steps=len(row["trajectory"])))
    alignment = Counter()
    for block in pairs.values():
        if len(block) == 4:
            alignment.update(total=1, matching_rng=int(len({digest(root["rng"]) for root in block}) == 1),
                             changed_hand=int(len({tuple(root["hand"]) for root in block}) > 1))
    interactions = factorial_bounds(outcomes)
    return dict(status=status, slices=slices, paired_opening=alignment, d11_play_exposure=exposure,
                truncated=capped, factorial_bounds=interactions,
                winning_hp={group: dict(n=len(hps), median=median(hps), mean=mean(hps))
                            for group, hps in winning_hp.items()})


def factorial_bounds(outcomes):
    coefficients = {(0, 0): 1, (1, 0): -1, (0, 1): -1, (1, 1): 1}
    by_family = defaultdict(list)
    for (group, _), arms in outcomes.items():
        if len(arms) != 4:
            continue
        known = sum(coefficients[arm] * label for arm, label in arms.items() if label is not None)
        missing_weights = [coefficients[arm] for arm, label in arms.items() if label is None]
        by_family[group].append((known, missing_weights))
    result = {}
    for group, blocks in by_family.items():
        complete = [known for known, missing in blocks if not missing]
        result[group] = dict(blocks=len(blocks), complete=len(complete),
                             complete_mean=mean(complete) if complete else None,
                             lower=mean(known + sum(min(weight, 0) for weight in missing)
                                        for known, missing in blocks),
                             upper=mean(known + sum(max(weight, 0) for weight in missing)
                                        for known, missing in blocks))
    return result


def contrasts(model):
    groups = defaultdict(list)
    for block in model["factorial"]:
        for key in ("all", block["family"], f'{block["family"]}/{block["encounter"]}', block["recipe"]):
            groups[key].append(block)
    return {key: dict(n=len(values), observed=mean(b["observed"] for b in values),
                      predicted=mean(b["predicted"] for b in values),
                      error=mean(abs(b["observed"]-b["predicted"]) for b in values),
                      nonzero=sum(b["observed"] != 0 for b in values),
                      observed_cells=[mean(b["observed_cells"][i] for b in values) for i in range(4)],
                      predicted_cells=[mean(b["predicted_cells"][i] for b in values) for i in range(4)])
            for key, values in groups.items()}


def package(output):
    ledger = rows(output / "ledger.jsonl")
    budget = rows(output / "budget.jsonl")
    native = rows(output / "native.jsonl")
    manifest = read(HERE / "manifest.json")
    cases = {item["case"]["id"]: item["case"] for item in manifest}
    protocol = read(HERE / "protocol.json")
    if len(budget) > protocol["execution_budget"] or len({(r["phase"], r["id"]) for r in budget}) != len(budget):
        raise ValueError("Invalid budget")
    if {(r["phase"], r["id"]) for r in budget} != {(r["phase"], r["id"]) for r in ledger + native}:
        raise ValueError("Budget and outcome ledgers differ")
    if any(cases[r["id"]]["cohort"] != r["phase"] for r in ledger):
        raise ValueError("Prediction recorded in the wrong split")
    for row in ledger + native:
        life = row.get("lifecycle")
        if life is not None and life["loaded"]["sha256"] != protocol["versions"]["solver_sha256"]:
            raise ValueError("Unexpected worker solver")
    timings = rows(output / "timings.jsonl")
    evaluation_path = output / "evaluation.json"
    model_path = output / "models.json"
    results = read(evaluation_path) if evaluation_path.exists() else None
    diagnostics = evidence(cases, ledger)
    episodes = [r["episode_ms"] for r in ledger if "episode_ms" in r]
    builds = [r["lifecycle"]["build"]["initialize_ms"] for r in ledger if r.get("lifecycle")]
    diagnostics.update(attempts=len(budget), timing=timings,
                       mean_rollout_ms=mean(episodes) if episodes else None,
                       median_rollout_ms=median(episodes) if episodes else None,
                       median_build_initialize_ms=median(builds) if builds else None,
                       peak_worker_bytes=max((r.get("memory") or 0 for r in ledger), default=0),
                       native=dict(count=len(native), public_points=sum(r.get("checked", 0) for r in native),
                                   field_diffs=sum(len(r.get("diffs", [])) for r in native)),
                       contrasts={f'{model["mode"]}/{model["groups"]}': contrasts(model)
                                  for model in results["results"]} if results else {})
    diagnostics["training_gate"] = training_qualification(
        diagnostics["status"].get("train", {}), protocol["split_counts"]["train"], protocol["stop"])
    archive(HERE / "ledger.json.gz", dict(versions=read(output / "versions.json"), timings=timings,
                                           budget=budget, rows=ledger, native=native,
                                           manifest_sha256=digest(manifest)))
    completed = Counter(r["phase"] for r in ledger)
    data_by_phase = {phase: data(output, phase) for phase, count in completed.items()
                     if count == protocol["split_counts"][phase]}
    archive(HERE / "data.json.gz", data_by_phase)
    artifacts = ["protocol.json", "manifest.json", "ledger.json.gz", "data.json.gz", "diagnostics.json"]
    if model_path.exists():
        archive(HERE / "models.json.gz", read(model_path))
        artifacts.append("models.json.gz")
    if results is not None:
        save(HERE / "evaluation.json", results)
        artifacts.append("evaluation.json")
    save(HERE / "diagnostics.json", diagnostics)
    save(HERE / "artifact-hashes.json", {name: (text_hash if name.endswith(".json") else file_hash)(HERE / name)
                                         for name in artifacts})
    print(json.dumps({k: v for k, v in diagnostics.items() if k not in ("contrasts", "truncated")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    package(parser.parse_args().output.resolve())
