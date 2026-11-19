"""Summarize recorded paired results without opening root archives."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from statistics import median

MODES = {"fixed": "fixed", "same_seed": "fixed", "adaptive": "adaptive"}


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
    return {"n": len(values), "p50": median(values),
            "p90": values[lo] + (pos - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo])}


def total(row, mode, key):
    first = row["first"].get(MODES[mode], {})
    quality = row["refine"].get(mode) or {}
    if first.get(key) is None or quality.get(key, 0) is None or "fault" in row:
        return None
    return first[key] + quality.get(key, 0)


def summarize(rows):
    summary = dict(n=len(rows), faults=sum("fault" in r for r in rows), first={}, combined={}, hp_delta={})
    for column in ("handshake_ms", "initialize_ms", "snapshot_ms", "root_ms"):
        summary[column] = distribution([r["root_timing"][column] for r in rows if "root_timing" in r])
    for arm in ("fixed", "adaptive"):
        attempts = [r["first"].get(arm, {}) for r in rows]
        wins = [a["winner"] for a in attempts if "winner" in a]
        summary["first"][arm] = dict(
            status=dict(Counter(a.get("status", "not_run") for a in attempts)),
            hp_lost=distribution([a["hp_lost"] for a in wins]), predator_terminal=sum(a["predator_terminal"] for a in wins),
            **{k: distribution([a[k] for a in attempts if a.get(k) is not None])
               for k in ("transitions", "prepare_ms", "hot_ms", "rpc_ms")})
    for mode in MODES:
        choices = [r["pareto"][mode]["512"] for r in rows]
        summary["combined"][mode] = dict(
            chosen_hp_lost=distribution([c["hp_lost"] for c in choices if c]),
            stops=dict(Counter((r["refine"].get(mode) or {}).get("status", "not_run") for r in rows)),
            **{k: distribution([x for r in rows if (x := total(r, mode, k)) is not None])
               for k in ("transitions", "hot_ms", "prepare_ms", "rpc_ms")})
    for cap in ("128", "256", "512"):
        caps = summary["hp_delta"][cap] = {}
        for mode in ("same_seed", "adaptive"):
            outcomes = Counter()
            for row in rows:
                a, b = (row["pareto"][name][cap] for name in ("fixed", mode))
                if not a or not b:
                    outcomes["neither" if not a and not b else "lost_win" if a else "new_win"] += 1
                else:
                    difference = b["hp"] - a["hp"]
                    outcomes["better" if difference > 0 else "worse" if difference < 0 else "equal"] += 1
            caps[mode] = dict(outcomes)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development", type=Path)
    parser.add_argument("validation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    development, validation = (read(p)["rows"] for p in (args.development, args.validation))
    groups = {
        "development": [r for r in development if r["stress_hp"] is None],
        "stress": [r for r in development if r["stress_hp"] is not None],
        "validation": validation,
    }
    args.output.write_text(json.dumps({k: summarize(v) for k, v in groups.items()}, indent=2) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
