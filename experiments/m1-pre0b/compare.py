"""Compare new trajectories with PRE0 at the original ordinal and private root recipe."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def records(connection):
    for ordinal, payload, recipe, sha in connection.execute("""
            SELECT ordinal, payload, recipe, sha FROM trajectories
            JOIN private_tasks USING(id) ORDER BY ordinal
            """):
        data = gzip.decompress(payload)
        if sha256(data).hexdigest() != sha:
            raise ValueError(f"Invalid payload digest at {ordinal}")
        yield ordinal, json.loads(data), json.loads(recipe)


def key(record):
    if record["complete"]:
        return "complete"
    return f'{record["status"]}:{record["reason"]}'


def unchanged(old, new, tolerance):
    if (any(old[k] != new[k] for k in ("terminal", "status", "length", "behavior"))
            or len(old["steps"]) != len(new["steps"])):
        return False
    for a, b in zip(old["steps"], new["steps"], strict=True):
        if (any(a[k] != b[k] for k in ("observation", "action", "position", "advanced"))
                or abs(a["behavior_logp"] - b["behavior_logp"]) > tolerance):
            return False
    return True


def truncation_progress(record):
    observations = [step["observation"] for step in record["steps"]]
    last = observations[-1]
    turns = sorted({obs["turn"] for obs in observations})
    recent = {turn: next(obs for obs in reversed(observations) if obs["turn"] == turn)
              for turn in turns[-5:]}
    return dict(encounter=record["root"]["encounter"], turn=last["turn"],
                tail_hp=[obs["hp"] for obs in recent.values()],
                tail_enemy_hp=[sum(enemy["hp"] for enemy in obs["enemies"]) for obs in recent.values()])


def compare(baseline, candidate, tolerance=2e-6):
    outcomes = {}
    totals = Counter()
    boss = Counter()
    truncated = []
    changed = []
    with closing(sqlite3.connect(baseline.resolve().as_uri()+"?mode=ro", uri=True)) as old_db, \
            closing(sqlite3.connect(candidate.resolve().as_uri()+"?mode=ro", uri=True)) as new_db:
        for before, after in zip(records(old_db), records(new_db)):
            ordinal, old, recipe = before
            new_ordinal, new, new_recipe = after
            if ordinal != new_ordinal or recipe != new_recipe:
                raise ValueError(f"Unpaired private root at ordinal {ordinal}")
            totals["paired"] += 1
            outcomes.setdefault(key(old), Counter())[key(new)] += 1
            if old["status"] == "truncated":
                truncated.append(dict(ordinal=ordinal, before=truncation_progress(old),
                                      outcome=key(new), length=new["length"]))
            if old["complete"] and new["complete"]:
                match = unchanged(old, new, tolerance)
                totals["complete_paired"] += 1
                totals["complete_match"] += int(match)
                if not match:
                    changed.append(ordinal)
            if new["complete"] and recipe["act"] == 2 and new["room"] == "Boss":
                boss[recipe["encounter"]] += 1
    return dict(totals=totals, outcomes=outcomes, act2_complete_boss=boss,
                old_truncated=truncated, changed_complete_ordinals=changed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.baseline, args.candidate), indent=2))
