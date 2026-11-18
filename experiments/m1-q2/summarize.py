"""Verify deterministic repetitions and separate terminal and unsupported results."""
import argparse
import collections
import json
import statistics

from benchmark import ROOTS, load

METRICS = ("decisionMs", "observeMs", "executeMs", "battleMs", "setupMs", "warmMs",
           "processMs", "peakMiB")
H1_ROOTS = {
    "dev-02-defect-elite": "4d5e409fbc5bcf6cfff29d46aa0d9ca415d4831d38996e7f55fc447338484bf4",
    "dev-00-ironclad-elite": "e377d2ee2aeb7069daa85a39ee5d9f74c1fcaa8d393fd13a8c6e43b5dfd58f4b",
}


def compact(directory, cases, repaired):
    rows = load(directory / "results.json")
    groups = collections.defaultdict(list)
    roots = {}
    seeds = {}
    assert len(rows) == len(cases) * 4
    for row in rows:
        root = row["case"]
        assert seeds.setdefault(root, row["seed"]) == row["seed"]
        identity = (row["root"], row["live"], row["fixtureSha"])
        assert roots.setdefault(root, identity) == identity
        if root in H1_ROOTS:
            assert identity[:2] == (H1_ROOTS[root], H1_ROOTS[root])
        if row["status"] == "win":
            result = row["outcome"]
            assert result["combatEnded"] and result["survived"] and result["finalEnemyHp"] == 0
        if row["status"] == "death":
            assert row["outcome"]["finalHp"] == 0
        if row["exitCode"] == 0:
            assert not row["outcome"]["potions"]
        groups[root, row["policy"]].append(row)
    assert set(roots) == set(cases) and len(set(seeds.values())) == len(cases)
    output = []
    for (root, policy), samples in sorted(groups.items()):
        assert sorted(s["repeat"] for s in samples) == [0, 1]
        row = samples[0]
        evidence = ("status", "outcome", "endTurn", "actions", "trajectory",
                    "initialResources", "finalResources", "failure", "exitCode")
        for field in evidence:
            assert row.get(field) == samples[1].get(field), (root, policy, field)
        if repaired:
            assert all(s["reattachVisualCalls"] == (1 if policy == "tactical" else 0) for s in samples)
        if row["status"] == "unsupported_reattach":
            assert "outcome" not in row
        entry = {k: row[k] for k in ("case", "policy", "seed", "character", "encounterKind",
                                     "ascension", "root", "live", "fixtureSha", *evidence) if k in row}
        stem = directory / f"{root}-{policy}-{row['repeat']}" / "harness-result.json"
        if stem.exists():
            entry["encounter"] = load(stem)["scenario"]["EncounterId"]
        if "trajectory" in entry:
            for index, step in enumerate(entry["trajectory"]):
                card = (step["selected"] or {}).get("id")
                relevant = (index == len(entry["trajectory"]) - 1 or card == "THE_GAMBIT"
                            or any(move["id"] == "FRANTIC_ESCAPE" for move in step["moves"]))
                if not relevant:
                    step.pop("moves")
        entry["timing"] = {key: [round(fn(s[key] for s in samples), 6) for fn in (min, statistics.median, max)]
                           for key in METRICS if key in row}
        if repaired:
            entry["reattachVisualCalls"] = row["reattachVisualCalls"]
        output.append(entry)
    return output


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("repair", type=Path)
    args = parser.parse_args()
    baseline = compact(args.baseline, ROOTS, repaired=False)
    repair = compact(args.repair, ("dev-00-ironclad-elite",), repaired=True)
    decim = {r["policy"]: r for r in baseline if r["case"] == "dev-00-ironclad-elite"}
    for row in repair:
        assert row["root"] == decim[row["policy"]]["root"]
        assert row["live"] == decim[row["policy"]]["live"]
        if row["policy"] == "first":
            assert row["trajectory"] == decim["first"]["trajectory"]
        else:
            assert row["status"] == "death"
            assert not any(e["id"] == 1 for s in row["trajectory"] if s["turn"] == 4 for e in s["enemies"])
            assert any(e["id"] == 1 and e["hp"] == 25 for s in row["trajectory"] if s["turn"] == 5 for e in s["enemies"])
    print(json.dumps({"scope": "public-observation-native",
                      "timingOrder": ["min", "median", "max"],
                      "baseline": baseline, "isolatedPresentationRepair": repair}, indent=2))
