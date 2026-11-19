"""Summarize all allocated pilot positions, including failures."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from statistics import median


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values):
    values = sorted(values)
    if not values:
        return None
    pos = .9 * (len(values) - 1)
    lo = int(pos)
    return dict(n=len(values), p50=median(values),
                p90=values[lo] + (pos - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo]))


def status(row):
    return row.get("first", {}).get("status", row.get("failure", {}).get("status", row["outcome"]))


def cohort(data):
    rows = data["rows"]
    elapsed = data["elapsed_ms"]
    cold = [r for r in rows if r["started_cold"]]
    warm = [r for r in rows if not r["started_cold"]]
    restarted = cold[1:]
    return dict(samples=len(rows), elapsed_ms=elapsed, records_per_second=1000 * len(rows) / elapsed,
                root_valid=sum("root_sha256" in row for row in rows),
                wins=sum(row["outcome"] == "predicted_win" for row in rows),
                status=dict(Counter(status(r) for r in rows)),
                branch_stops=dict(Counter(branch["stop"] for r in rows for branch in r.get("first", {}).get("routes", []))),
                recycle_causes=dict(Counter(r["discard_reason"] for r in rows if r.get("discard_reason"))),
                cold=len(cold), warm=len(warm),
                recovery_launch_ms=sum(r["launch_ms"] for r in restarted),
                recovery_model_ms=sum(r.get("native_phases_ms", {}).get("model_init", 0) for r in restarted),
                f4_completed=sum(r.get("quality") is not None and not r.get("quality_incomplete") for r in rows),
                peak_working_set_bytes=max((r.get("peak_working_set_bytes") or 0) for r in rows),
                groups={tier: dict(
                    status=dict(Counter(status(r) for r in group)),
                    elapsed_ms=stats([r["elapsed_ms"] for r in group]),
                    hot_ms=stats([r["first"]["hot_ms"] for r in group if "hot_ms" in r.get("first", {})]),
                    transitions=stats([r["first"]["transitions"] for r in group
                                       if r.get("first", {}).get("transitions") is not None]))
                    for tier in sorted({r["input"]["complexity"] for r in rows})
                    for group in [[r for r in rows if r["input"]["complexity"] == tier]]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("evidence", nargs="+", type=Path)
    args = parser.parse_args()
    names = [p.parent.name if p.name == "results.json" else p.name.split(".", 1)[0]
             for p in args.evidence]
    if len(set(names)) != len(names):
        raise ValueError("Evidence names must be distinct")
    report = {name: cohort(read(p)) for name, p in zip(names, args.evidence, strict=True)}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
