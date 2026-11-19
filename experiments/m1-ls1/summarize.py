"""Validate complete reports, then publish paired quality/cost and compact ledgers."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from statistics import mean, median

from ls1_design import HERE, PROTOCOL, ENCOUNTERS, digest, file_hash, read, verify_groups
from loop import MODES, read_records, specs, validate_experiment_rows
from search import bank

PHASES = ("pilot", "collect", "report", "feedback")


def describe(values):
    values = sorted(x for x in values if x is not None)
    if not values:
        return None
    return dict(n=len(values), mean=mean(values), median=median(values),
                min=values[0], max=values[-1])


def flattened(records):
    yield from (e for row in records for e in row["experience"])


def measure(results, n):
    outcomes = [r["outcome"] for r in results]
    wins = [r for r in outcomes if r["status"] == "qualified_win"]
    statuses = Counter(r["status"] for r in outcomes)
    if n > len(results):
        statuses["unrecorded_failure"] = n - len(results)
    resources = [w["locked"] for w in wins]
    return dict(roots=n, win=len(wins), statuses=dict(statuses),
                planned_changes=sum(r["order_changed"] for r in outcomes),
                executed_changes=sum(r["executed_order_changed"] for r in outcomes),
                fallback=dict(Counter(r["audit"]["fallback"] for r in results if r["audit"]["fallback"])),
                first_transitions=describe(r["first_transitions"] for r in wins),
                first_verified_transitions=describe(r["first_transitions"] + r["verification_transitions"] for r in wins),
                first_ms=describe(r["first_ms"] for r in wins),
                qualified_first_ms=describe(r["qualified_first_ms"] for r in wins),
                total_transitions=describe(r["transitions"] for r in outcomes),
                search_ms=describe(r["search_ms"] for r in outcomes),
                ordering_ms=describe(r["ordering_ms"] for r in outcomes),
                model_ms=describe(r["model_ms"] for r in outcomes),
                hp=describe(r["hp"] for r in resources),
                max_hp=describe(r["max_hp"] for r in resources),
                hp_lost=describe(r["hp_lost"] for r in resources),
                gold=describe(r["gold"] for r in resources),
                potions=describe(sum(p is not None for p in r["potions"]) for r in resources),
                route_risks=dict(Counter(risk for r in outcomes for risk in r["route_risks"])))


def paired(rows, mode):
    result = Counter()
    spent, elapsed, hp, gold, potions = [], [], [], [], []
    for base, treatment in rows:
        a = base and base["status"] == "qualified_win"
        b = treatment and treatment["status"] == "qualified_win"
        if base is None or treatment is None:
            result["unrecorded_pair"] += 1
        elif a and b:
            result["both"] += 1
            hp.append(treatment["locked"]["hp"] - base["locked"]["hp"])
            gold.append(treatment["locked"]["gold"] - base["locked"]["gold"])
            potions.append(sum(p is not None for p in treatment["locked"]["potions"]) -
                           sum(p is not None for p in base["locked"]["potions"]))
            spent.append(treatment["first_transitions"] - base["first_transitions"])
            elapsed.append(treatment["first_ms"] - base["first_ms"])
            result["different_first_route"] += int(base["first_key"] != treatment["first_key"])
        else:
            result["baseline_only" if a else "treatment_only" if b else "neither"] += 1
    return dict(mode=mode, counts=dict(result), hp_delta=describe(hp), gold_delta=describe(gold),
                potion_delta=describe(potions), first_transitions_delta=describe(spent),
                first_search_ms_delta=describe(elapsed))


def curves(roots):
    output = {}
    for cap in PROTOCOL["budgets"]:
        by_id = {r["id"]: {e["audit"]["mode"]: e for e in r["experience"] if e["outcome"]["cap"] == cap}
                 for r in roots}
        arms = {mode: measure([row[mode] for row in by_id.values() if mode in row], len(roots)) for mode in MODES}
        for mode in MODES[1:]:
            arms[mode]["paired"] = paired(
                [(row.get("baseline_search", {}).get("outcome"), row.get(mode, {}).get("outcome"))
                 for row in by_id.values()], mode)
        output[str(cap)] = arms
    return output


def summarize(out, destination):
    contract = read(out / "contract.json")
    cases = contract["manifest"]
    versions = contract["versions"]
    groups = {"pilot": {"pilot"}, "collect": {"train", "selection"}, "report": {"report", "reachable"},
              "feedback": {"feedback"}}
    ledger = {phase: read_records(out, phase, [c for c in cases if c["split"] in groups[phase]])
              for phase in PHASES}
    validate_experiment_rows([r for rows in ledger.values() for r in rows], cases, versions)
    lookup = {c["id"]: c for c in cases}
    verify_groups([lookup[r["id"]] | {"root_stamp": r.get("live_stamp")} for rows in ledger.values() for r in rows])
    for phase, rows in ledger.items():
        for root in rows:
            exp = root["experience"]
            expected = [(mode, first, cap, teacher) for mode, first, cap, teacher in specs(phase, lookup[root["id"]])]
            actual = [(e["audit"]["mode"], e["outcome"]["first_cap"], e["outcome"]["cap"],
                       e["outcome"]["candidate_probe"]) for e in exp]
            if actual != expected[:len(actual)] or len(actual) != len(expected) and not root["failure"]:
                raise ValueError(f"Unexpected run matrix for {root['id']}")
    frozen = read(out / "model-v1.json")
    updated = read(out / "model-v2.json")
    if updated["provenance"]["parent"] != frozen["sha256"]:
        raise ValueError("Feedback lineage mismatch")
    for e in flattened(ledger["report"] + ledger["feedback"]):
        if e["audit"]["mode"] in ("learned_search", "card_id") and e["audit"]["model_sha256"] != frozen["sha256"]:
            raise ValueError("Report used an unregistered model")
    report = ledger["report"]
    open_roots = [r for r in report if lookup[r["id"]]["split"] == "report"]
    slices = defaultdict(list)
    for row in open_roots:
        case = lookup[row["id"]]
        slices[case["spec"]["character"]].append(row)
        encounter = case["spec"]["encounter"]
        slices[encounter].append(row)
        slices["unseen_encounters" if encounter in ENCOUNTERS[2:] else "seen_encounters"].append(row)
    stats = {}
    for phase, rows in ledger.items():
        all_exp = list(flattened(rows))
        stats[phase] = dict(roots=len(rows), cells=len(all_exp), transitions=sum(e["outcome"]["transitions"] for e in all_exp),
                            wall_seconds=read(out / (phase + "-duration.json"))["seconds"],
                            root_wall_ms=describe(r["root_wall_ms"] for r in rows),
                            build_ms=describe(r["build_ms"] for r in rows),
                            statuses=dict(Counter(e["outcome"]["status"] for e in all_exp)),
                            candidate_stops=dict(Counter(a["status"] for e in all_exp for a in e["outcome"]["attempts"])),
                            failures=[dict(id=r["id"], **r["failure"]) for r in rows if r["failure"]])
    summary = dict(contract_sha256=digest(contract), versions=versions, phases=stats,
                   training_seconds=read(out / "train-duration.json")["seconds"],
                   model_provenance=[{k: payload[k] for k in ("sha256", "numpy", "provenance")} |
                                     {"selection": {mode: {k: value[k] for k in (
                                         "epochs", "selection_mse", "parameters_per_seed")}
                                          for mode, value in payload["models"].items()}}
                                     for payload in (frozen, updated)],
                   report=curves(open_roots), slices={name: curves(rows) for name, rows in sorted(slices.items())},
                   reachable=curves([r for r in report if lookup[r["id"]]["split"] == "reachable"]))
    if destination.exists():
        raise ValueError("Destination already exists")
    destination.mkdir(parents=True)
    bank.atomic(destination / "summary.json", summary)
    bank.atomic(destination / "contract.json", contract)
    with (destination / "ledger.json.gz").open("xb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(json.dumps(ledger, separators=(",", ":"), ensure_ascii=False).encode())
    for idx, payload in enumerate((frozen, updated), 1):
        bank.atomic(destination / f"model-v{idx}.json", payload)
    files = sorted(destination.iterdir())
    bank.atomic(destination / "artifact-hashes.json", {p.name: file_hash(p, normalize=p.suffix == ".json") for p in files})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    summarize(args.input, args.destination)
