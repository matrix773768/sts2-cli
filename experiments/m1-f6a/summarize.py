"""Aggregate phase totals, paired warm distributions and serialized batch throughput."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
from statistics import median


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    pos = .9 * (len(values) - 1)
    lo = int(pos)
    return dict(n=len(values), p50=median(values),
                p90=values[lo] + (pos - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo]))


def timings(rows):
    columns = {
        "quality_hot_ms": lambda r: r["quality"]["hot_ms"],
        "quality_preparation_ms": lambda r: r["quality"]["prepare_ms"],
        "quality_rpc_ms": lambda r: r["quality"]["rpc_ms"],
        "first_hot_ms": lambda r: r["first"]["hot_ms"],
        "retirement_ms": lambda r: r["retirement"]["elapsed_ms"],
        "root_wall_ms": lambda r: r["root_wall_ms"],
        "quality_transitions": lambda r: r["quality"]["transitions"],
        "quality_thread_allocated_bytes": lambda r: r["runtime"]["thread_allocated_bytes"],
        "quality_gc_pause_ms": lambda r: r["runtime"]["gc_pause_ms"],
        "working_set_bytes": lambda r: r["working_set_bytes"],
        "peak_working_set_bytes": lambda r: r["peak_working_set_bytes"],
    }
    return {key: distribution(get(row) for row in rows) for key, get in columns.items()}


def phases(rows):
    adapter, solver = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    wire = defaultdict(float)
    for row in rows:
        for key, scope in row["profile"]["adapter"].items():
            for stat, value in scope.items():
                adapter[key][stat] += value
        for key, scope in row["profile"]["solver"].items():
            for stat, value in scope.items():
                solver[key][stat] += value
        solver["Fork"]["count"] += row["profile"]["forks"]
        for key, value in row["wire"].items():
            wire[key] += value
        wire["count"] += 1
    for collection in (adapter, solver):
        for phase in collection.values():
            if phase.get("count"):
                phase["us_per_call"] = 1000 * phase["ms"] / phase["count"]
    duplicates = sum(sum(a.get("win_key") is not None for a in row["quality"]["attempts"])
                     - len(row["quality"]["candidates"]) for row in rows)
    return dict(root_count=len(rows), adapter=adapter, solver=solver, wire=wire,
                duplicate_winning_routes=duplicates,
                charged=sum(r["quality"]["transitions"] for r in rows),
                reused_prefix_transitions=sum(r["quality"]["reused_prefix_transitions"] for r in rows),
                heat_ms=sum(r["quality"]["hot_ms"] for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paired", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--local", type=Path)
    args = parser.parse_args()
    paired, profile = read(args.paired), read(args.profile)
    result = dict(paired={}, profile={})
    for lean, key in ((False, "frozen"), (True, "lean")):
        batches = [c for c in paired["cohorts"] if c["lean"] == lean]
        rows = [r for b in batches for r in b["rows"][1:]]
        result["paired"][key] = dict(
            batches=[dict(elapsed_ms=b["elapsed_ms"], n=len(b["rows"]),
                          throughput=1000 * len(b["rows"]) / b["elapsed_ms"]) for b in batches],
            first=timings([b["rows"][0] for b in batches]),
            warm=timings(rows),
            groups={tier: timings([r for r in rows if r["input"]["complexity"] == tier])
                    for tier in ("simple", "complex")},
            total_warm_heat_ms=sum(r["quality"]["hot_ms"] for r in rows),
            total_warm_root_ms=sum(r["root_wall_ms"] for r in rows),
            total_warm_allocated_bytes=sum(r["runtime"]["thread_allocated_bytes"] for r in rows),
            total_warm_gc=[sum(r["runtime"]["gc_collections"][i] for r in rows) for i in range(3)],
            total_warm_gc_pause_ms=sum(r["runtime"]["gc_pause_ms"] for r in rows))
        p = [c for c in profile["cohorts"] if c["lean"] == lean][0]["rows"]
        result["profile"][key] = dict(first=phases(p[:1]), warm=phases(p[1:]))
    if args.local:
        rows = read(args.local)["cohorts"][0]["rows"]
        pairs = [r["same_source_pair"]["timings"] for r in rows[1:]]
        result["same_source"] = {
            name: distribution([pair[key]["hot_ms"] for pair in pairs])
            for name, key in (("frozen", "false"), ("lean", "true"))
        }
        result["same_source"]["paired_ms_saved"] = distribution(
            [pair["false"]["hot_ms"] - pair["true"]["hot_ms"] for pair in pairs])
        result["same_source"]["total_heat_ms"] = {
            name: sum(pair[key]["hot_ms"] for pair in pairs)
            for name, key in (("frozen", "false"), ("lean", "true"))
        }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
