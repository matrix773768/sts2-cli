"""Validate root and outcome invariants and condense timing evidence."""
import argparse
import json
from pathlib import Path
import statistics

H1_ROOTS = {
    "prisms": "4d5e409fbc5bcf6cfff29d46aa0d9ca415d4831d38996e7f55fc447338484bf4",
    "decimillipede": "e377d2ee2aeb7069daa85a39ee5d9f74c1fcaa8d393fd13a8c6e43b5dfd58f4b",
}


def summarize(rows):
    assert len(rows) == 24
    roots = {}
    trajectories = {}
    timings = {}
    for row in rows:
        case, policy = row["case"], row["policy"]
        key = f"{case}/{policy}"
        if row["status"] == "unsupported_native_host":
            trace = {k: row[k] for k in ("status", "exitCode", "failure")}
            assert trajectories.setdefault(key, trace) == trace
            timings.setdefault(key, []).append({k: row[k] for k in ("warm", "repeat", "processMs")})
            continue
        root = (row["root"], row["live"])
        assert roots.setdefault(case, root) == root
        if case in H1_ROOTS:
            assert root == (H1_ROOTS[case], H1_ROOTS[case])
        outcome = row["outcome"]
        assert row["ipcRequests"] == row["transitions"] == row["simulationMs"] == 0
        assert not outcome["potions"]
        if row["status"] == "win":
            assert outcome["combatEnded"] and outcome["survived"] and outcome["finalEnemyHp"] == 0
        trace = {k: row[k] for k in ("status", "actions", "endTurn", "outcome", "postCombatHp", "trajectory")}
        assert trajectories.setdefault(key, trace) == trace, (key, row["repeat"], row["warm"])
        timing = {k: v for k, v in row.items() if k.endswith("Ms") or k in ("warm", "repeat", "peakMiB")}
        timings.setdefault(key, []).append(timing)

    results = {}
    for key, samples in timings.items():
        distributions = {}
        for warm in (False, True):
            group = [sample for sample in samples if sample["warm"] == warm]
            assert len(group) == 2
            distributions["prewarmed" if warm else "cold"] = {
                metric: [round(value, 6) for value in (
                    min(sample[metric] for sample in group),
                    statistics.median(sample[metric] for sample in group),
                    max(sample[metric] for sample in group))]
                for metric in group[0] if metric.endswith("Ms") or metric == "peakMiB"
            }
        results[key] = trajectories[key] | {"timings": distributions, "samples": samples}
    assert results["small/tactical"]["status"] == "win"
    assert results["prisms/tactical"]["outcome"]["hpLost"] == 11
    assert results["prisms/tactical"]["endTurn"] == 5
    assert results["prisms/first"]["status"] == "death"
    assert results["decimillipede/first"]["status"] == "unsupported_choice"
    assert results["decimillipede/tactical"]["status"] == "unsupported_native_host"
    return {"scope": "public-observation-native", "distributionOrder": ["min", "median", "max"],
            "roots": roots, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.results.read_text(encoding="utf-8"))), indent=2))
