"""Summarize paired measurements by declared encounter complexity."""
import argparse
from collections import Counter
from pathlib import Path

from run_probe import bank


def distribution(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None

    def quantile(p):
        pos = p * (len(values) - 1)
        low = int(pos)
        return round(values[low] + (pos - low) * (values[min(low + 1, len(values) - 1)] - values[low]), 3)

    return dict(n=len(values), p50=quantile(.5), p90=quantile(.9), maximum=values[-1])


def complete(row):
    return (row["outcome"] == "predicted_win" and not row.get("quality_incomplete")
            and not row.get("discard_reason"))


def metrics(rows):
    columns = {
        "initialize_ms": lambda row: row.get("root_timing", {}).get("initialize_ms"),
        "model_ms": lambda row: row.get("native_phases_ms", {}).get("model_init"),
        "native_build_ms": lambda row: row.get("native_phases_ms", {}).get("native_build"),
        "predict_ms": lambda row: row.get("predict_ms"),
        "first_prepare_ms": lambda row: row.get("first", {}).get("prepare_ms"),
        "quality_prepare_ms": lambda row: (row.get("quality") or {}).get("prepare_ms"),
        "f3b_ms": lambda row: row.get("first", {}).get("hot_ms"),
        "f4_ms": lambda row: (row.get("quality") or {}).get("hot_ms"),
        "f3b_transitions": lambda row: row.get("first", {}).get("transitions"),
        "f4_transitions": lambda row: (row.get("quality") or {}).get("transitions"),
        "retire_ms": lambda row: row.get("retirement", {}).get("elapsed_ms"),
        "root_wall_ms": lambda row: row["root_wall_ms"],
        "working_set_bytes": lambda row: row.get("working_set_bytes"),
        "peak_working_set_bytes": lambda row: row.get("peak_working_set_bytes"),
    }
    return dict(n=len(rows), predictions_complete=sum(complete(row) for row in rows),
                failures=dict(Counter(row["failure"]["status"] for row in rows if "failure" in row)),
                discards=dict(Counter(row["discard_reason"] for row in rows if "discard_reason" in row)),
                first_status=dict(Counter(row.get("first", {}).get("status", "not_run") for row in rows)),
                quality_status=dict(Counter((row.get("quality") or {}).get("status", "not_run") for row in rows)),
                timing={key: distribution(get(row) for row in rows) for key, get in columns.items()})


def summarize(data):
    modes = {}
    for name in ("cold", "resident"):
        batch = data[name]
        rows = batch["rows"]
        groups = rows if name == "cold" else rows[1:]
        modes[name] = dict(planned=batch["planned"], attempted=len(rows), elapsed_ms=batch["elapsed_ms"],
                           completed_predictions_per_second=sum(complete(r) for r in rows)
                           * 1000 / batch["elapsed_ms"],
                           process_ids=len({r["pid"] for r in rows}),
                           groups={tier: metrics([r for r in groups if r["input"]["complexity"] == tier])
                                   for tier in ("simple", "complex")},
                           overall=metrics(rows))
        if name == "resident":
            modes[name]["first"] = metrics(rows[:1])
            modes[name]["first_cycle"] = metrics(rows[:6])
            modes[name]["second_cycle"] = metrics(rows[6:12])
            modes[name]["last_cycle"] = metrics(rows[-6:])
    return modes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    bank.atomic(args.output, summarize(bank.read(args.results)))


if __name__ == "__main__":
    main()
