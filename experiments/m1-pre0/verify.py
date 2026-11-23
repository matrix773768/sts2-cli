"""Verify public contracts, transaction pairing, and optional paired replay."""
import argparse
from collections import Counter
from contextlib import closing
import json
from itertools import islice
import math
from pathlib import Path
import sqlite3

from dataset import batches


def verify(path, reference=None, tolerance=0.0, limit=None):
    counts, rooms, cards, exclusions = Counter(), Counter(), Counter(), Counter()
    splits, lengths, hp, reasons, mechanics = (Counter() for _ in range(5))
    family_splits = {}
    decisions = 0
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        for left, right in (("trajectories", "private_tasks"), ("private_tasks", "trajectories")):
            missing = db.execute(f"SELECT id FROM {left} EXCEPT SELECT id FROM {right} LIMIT 1").fetchone()
            if missing:
                raise ValueError("Unpaired trajectory and isolated metadata")

    def records(source):
        stream = (record for group in batches(source, complete=False) for record in group)
        return islice(stream, limit)

    other = records(reference) if reference else None
    for record in records(path):
        counts[record["status"]] += 1
        if record["reason"] is not None:
            reasons[f'{record["status"]}:{record["reason"]}'] += 1
        if family_splits.setdefault(record["family"], record["split"]) != record["split"]:
            raise ValueError("Deck family crosses splits")
        exclusions.update(record["unsupported_cards"])
        if "seed" in record["root"] or record["evidence"] != "prediction_only":
            raise ValueError("Unexpected public root metadata")
        if record["complete"]:
            if record["status"] not in ("predicted_win", "death") or not record["terminal"]:
                raise ValueError("Incomplete prediction marked complete")
            terminal = record["terminal"]
            if (not isinstance(terminal["turn"], int) or not isinstance(terminal["hp"], int)
                    or not 0 <= terminal["hp"] <= terminal["max_hp"]
                    or record["status"] == "predicted_win" and terminal["hp"] == 0):
                raise ValueError("Invalid predicted terminal resources")
            decisions += record["length"]
            hp[record["root"]["hp"]] += 1
            mechanics.update(record["mechanism_qualification"].values())
            cards.update(record["visible_cards"])
            rooms.update((f'{record["root"]["act"]}:{record["room"]}:{record["root"]["encounter"]}',))
            splits[record["split"]] += 1
            lengths[record["length"]] += 1
        if len(record["steps"]) != record["length"]:
            raise ValueError("Trajectory length mismatch")
        for i, step in enumerate(record["steps"]):
            menu = step["observation"]["actions"]
            if ([action["index"] for action in menu] != list(range(len(menu)))
                    or step["position"] != i or step["action"] not in menu
                    or not math.isfinite(step["behavior_logp"])
                    or record["complete"] and not step["advanced"]):
                raise ValueError("Invalid public decision")
        if other is not None:
            expected = next(other)
            fields = ("root", "split", "family", "behavior", "status", "reason", "complete",
                      "terminal", "cumulative_loss", "solver_gaps", "length", "visible_cards")
            if any(record[k] != expected[k] for k in fields):
                raise ValueError(f"Paired semantic mismatch at {record['id']}")
            for actual, wanted in zip(record["steps"], expected["steps"], strict=True):
                if (any(actual[k] != wanted[k] for k in ("position", "advanced", "observation", "action"))
                        or abs(actual["behavior_logp"] - wanted["behavior_logp"]) > tolerance):
                    raise ValueError(f"Paired decision mismatch at {record['id']}:{actual['position']}")
    if other is not None and next(other, None) is not None:
        raise ValueError("Paired sample counts differ")
    return dict(attempted=sum(counts.values()), complete=sum(splits.values()), decisions=decisions,
                statuses=counts, splits=splits, encounters=rooms, visible_cards=cards,
                outside_allowlist=exclusions, lengths=lengths, paired=reference is not None,
                hp=hp, reasons=reasons, mechanism_qualification=mechanics, families=len(family_splits))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(verify(args.dataset, args.reference, args.tolerance, args.limit), indent=2))
