"""Check choice coverage, original roots and deterministic native replay."""
import argparse
import collections
import json
from pathlib import Path
import statistics

from benchmark import ROOTS, load

METRICS = ("decisionMs", "choiceDecisionMs", "observeMs", "choiceObservationMs",
           "executeMs", "battleMs", "setupMs", "warmMs", "processMs", "peakMiB")
HISTORY = Path(__file__).resolve().parents[1] / "m1-q2" / "results.json"
PATH_FIELDS = ("status", "choiceFailure", "choiceRequests", "choiceChecks",
               "trajectory", "actions", "endTurn", "outcome", "initialResources", "finalResources")


def pair_rows(directory, expected):
    groups = collections.defaultdict(list)
    for row in load(directory / "results.json"):
        groups[row["case"], row["policy"]].append(row)
    assert set(groups) == expected
    for key, samples in groups.items():
        assert sorted(row["repeat"] for row in samples) == [0, 1]
        for field in ("root", "live", *PATH_FIELDS):
            assert samples[0].get(field) == samples[1].get(field), (key, field)
    return groups


def compact(directory, verification):
    historical_rows = load(HISTORY)["baseline"]
    history = {(r["case"], r["policy"]): r for r in historical_rows}
    groups = pair_rows(directory, {(root, mode) for root in ROOTS for mode in ("first", "tactical")})
    output = []
    counts = collections.Counter()
    for key, samples in sorted(groups.items()):
        row = samples[0]
        old = history[key]
        assert (row["root"], row["live"]) == (old["root"], old["live"]), key
        if row["status"] in ("win", "death"):
            outcome = row["outcome"]
            if row["status"] == "win":
                assert outcome["combatEnded"] and outcome["finalEnemyHp"] == 0 and outcome["survived"]
            else:
                assert not outcome["survived"] and outcome["finalHp"] == 0
            assert not outcome["potions"]
        checks = {check["step"]: check for check in row.get("choiceChecks", []) if "effect" in check}
        for req in row.get("choiceRequests", []):
            if "reason" in req:
                assert row["status"] == "unsupported_choice"
                continue
            indexes = req["indexes"]
            assert req["minSelect"] <= len(indexes) <= req["maxSelect"]
            assert len(indexes) == len(set(indexes))
            assert all(0 <= i < len(req["candidates"]) for i in indexes)
            assert checks[req["step"]]["effect"], (key, req)
            counts[req["action"]] += 1
        entry = {k: row[k] for k in ("case", "policy", "seed", "character", "encounterKind", "ascension",
                                     "root", "live", "fixtureSha", "failure", "reattachVisualCalls", *PATH_FIELDS) if k in row}
        entry["q2Status"] = old["status"]
        entry["timing"] = {name: [round(fn(s[name] for s in samples), 6)
                                  for fn in (min, statistics.median, max)]
                           for name in METRICS if name in row}
        if "decisionMs" in row:
            sums = [r["decisionMs"] + r["choiceDecisionMs"] for r in samples]
            entry["timing"]["totalPureDecisionMs"] = [min(sums), statistics.median(sums), max(sums)]
        for step in entry.get("trajectory", []):
            card = (step["selected"] or {}).get("id")
            if card != "THE_GAMBIT" and not any(m["id"] == "FRANTIC_ESCAPE" for m in step["moves"]):
                step.pop("moves")
        output.append(entry)

    checked = pair_rows(verification, {("dev-00-ironclad-elite", mode) for mode in ("first", "tactical")})
    sample = checked["dev-00-ironclad-elite", "first"][0]
    main_sample = groups["dev-00-ironclad-elite", "first"][0]
    for field in ("root", "live", "choiceRequests", "outcome", "actions"):
        assert sample[field] == main_sample[field]
    stamps = [check for check in sample["choiceChecks"] if "exactStateIncludingRng" in check]
    assert [s["step"] for s in stamps] == list(range(1, sample["actions"]))
    assert sample["status"] == "death" and sample["choiceRequests"]
    assert set(counts) == {"BURNING_PACT", "PURITY", "BEGONE", "DREDGE", "HEADBUTT"}
    return {"scope": "public-observation-native-with-choice",
            "timingOrder": ["min", "median", "max"],
            "verifiedExplicitChoicesByCard": dict(counts), "runs": output,
            "stateAndRngCheck": {"case": sample["case"], "policy": sample["policy"], "repeats": 2,
                                 "stamps": stamps, "terminal": sample["outcome"]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("verification", type=Path)
    args = parser.parse_args()
    print(json.dumps(compact(args.matrix, args.verification), indent=2))
