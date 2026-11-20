"""Read-only root-weighted HP reliability audit for completed reviews."""
import argparse
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import mean

from protocol import HERE
from nosl3b_store import unpack
from nosl_experience import save_json, targets


def hp_calibration(rows):
    roots = defaultdict(list)
    for r in rows:
        target = targets(r["feedback"])
        if target is not None and r["transitions"]:
            roots[r["root"]].append((r["transitions"][0]["value"][1], target[1]))
    pairs = [(mean(x for x, _ in items), mean(y for _, y in items)) for items in roots.values()]
    bins = defaultdict(list)
    for p, y in pairs:
        bins[min(4, int(p * 5))].append((p, y))
    detail = []
    for index, items in sorted(bins.items()):
        predicted = mean(p for p, _ in items)
        actual = mean(y for _, y in items)
        detail.append(dict(bin=index, roots=len(items), predicted=predicted, observed=actual,
                           bias=predicted-actual))
    return dict(roots=len(pairs), predicted_mean=mean(p for p, _ in pairs) if pairs else None,
                observed_mean=mean(y for _, y in pairs) if pairs else None, bins=detail,
                calibration_error=sum(b["roots"] * abs(b["bias"]) for b in detail) / len(pairs) if pairs else None)


def main(run, output):
    reports = sorted((run / "reviews").glob("u*/review-summary.json"))
    measures = {}
    with closing(sqlite3.connect((run / "training.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for path in reports:
            summary = json.loads(path.read_bytes())
            step = summary["update"]
            measure = {}
            for phase in ("selection", "report"):
                groups = {"sample": [], "greedy": []}
                with closing(db.execute("SELECT rows FROM roots WHERE phase=? AND step=?", (phase, step))) as rows:
                    for raw, in rows:
                        for row in unpack(raw)["rows"]:
                            if row["behavior"]["model_sha256"] != summary["model_sha256"]:
                                raise ValueError("Calibration ledger differs from reviewed model")
                            groups[row["mode"]].append(row)
                if any(groups.values()):
                    measure[phase] = {mode: hp_calibration(rows) for mode, rows in groups.items()}
            measures[str(step)] = measure
    save_json(output, dict(schema="sts2.nosl3c.hp-calibration.v1", checkpoints=measures))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    main(args.run.resolve(), args.output.resolve())