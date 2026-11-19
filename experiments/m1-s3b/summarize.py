"""Report development coverage and separate per-method diagnostic outcomes."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values):
    values = sorted(x for x in values if x is not None)
    if not values:
        return None
    pos = .9 * (len(values) - 1)
    lo = int(pos)
    return dict(n=len(values), p50=median(values),
                p90=values[lo] + (pos - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo]))


def categorize(rows):
    first = [r.get("first", {}) for r in rows]
    routes = Counter()
    initial, diagnoses = Counter(), Counter()
    for attempt in first:
        outcomes = attempt.get("routes", [])
        routes.update(r["stop"] for r in outcomes)
        failure = next((r for r in outcomes if r["stop"] != "predicted_win"), None)
        if failure:
            initial[failure["stop"]] += 1
            diagnoses.update((failure.get("failure") or {}).get("failure_type", []))
    return dict(n=len(rows), built=sum("root_sha256" in r for r in rows),
                outcomes=dict(Counter(a.get("status", r.get("failure", {}).get("status", "not_run"))
                                      for r, a in zip(rows, first, strict=True))),
                branch_stops=dict(routes), first_failed_rollout=dict(initial),
                first_failure_hypotheses=dict(diagnoses),
                first_hot_ms=stats([a.get("hot_ms") for a in first]),
                transitions=stats([a.get("transitions") for a in first]),
                winners_hp=stats([a["winner"]["hp"] for a in first if "winner" in a]),
                winners_wounds=stats([a["winner"]["hp_lost"] for a in first if "winner" in a]))


def production(data):
    rows = data["rows"]
    cold = [r for r in rows if r["started_cold"]]
    return dict(elapsed_ms=data["elapsed_ms"], n=len(rows), records_per_second=len(rows) * 1000 / data["elapsed_ms"],
                cold=len(cold), warm=len(rows) - len(cold), resets_due_to_failure=sum(
                    bool(r.get("discard_reason")) for r in rows),
                extra_cold_launch_ms=sum(r["launch_ms"] for r in cold[1:]),
                extra_cold_model_ms=sum(r.get("native_phases_ms", {}).get("model_init", 0) for r in cold[1:]),
                peak_working_set_bytes=max((r.get("peak_working_set_bytes") or 0) for r in rows),
                longest_worker_positions=max(Counter(r.get("pid") for r in rows).values()),
                root_wall_ms=stats([r["elapsed_ms"] for r in rows]))


def diagnostic(data):
    modes = defaultdict(list)
    groups = defaultdict(list)
    for row in data["rows"]:
        groups[row["group"]].append(row)
        for attempt in row["runs"]:
            modes[attempt["method"]].append(attempt)
    return dict(groups={name: dict(n=len(rows), result=dict(Counter(r["diagnosis"] for r in rows)))
                        for name, rows in groups.items()},
                methods={mode: dict(n=len(rows), outcomes=dict(Counter(r["status"] for r in rows)),
                                   hot_ms=stats([r.get("hot_ms") for r in rows]),
                                   transitions=stats([r.get("transitions") for r in rows]),
                                   elapsed_ms=stats([r["elapsed_ms"] for r in rows]))
                         for mode, rows in modes.items()},
                native=dict(Counter(r["status"] for r in data["native_audits"])),
                perturbations=dict(Counter(r["result"]["status"] for r in data["perturbations"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development", type=Path)
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    new = read(args.development)
    old = read(HERE.parent / "m1-s3a/hard.json.gz")
    rows = old["rows"] + new["rows"]
    if len(rows) != 96 or len({r["input"]["id"] for r in rows}) != 96:
        raise ValueError("Expected 96 distinct development inputs")
    result = dict(development=categorize(rows), production72=production(new),
                  diagnostics=diagnostic(read(args.diagnostics)), groups={})
    for dimension, get in {
        "character": lambda c: c["spec"]["character"],
        "encounter": lambda c: c["spec"]["encounter"],
        "template": lambda c: c["template"],
        "pressure": lambda c: c["complexity"],
        "resources": lambda c: "starter_relic_and_potion" if c["spec"]["relics"] else "empty",
        "template_encounter": lambda c: f"{c['template']}/{c['spec']['encounter']}",
    }.items():
        grouped = defaultdict(list)
        for row in rows:
            grouped[get(row["input"])].append(row)
        result["groups"][dimension] = {key: categorize(group) for key, group in grouped.items()}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
