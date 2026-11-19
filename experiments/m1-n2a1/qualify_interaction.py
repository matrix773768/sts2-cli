"""Repeat the frozen N2A workload with an explicit, deterministic discard decision."""
from collections import Counter
import gzip
import json
from pathlib import Path
from time import perf_counter_ns

from interaction import Episode
import qualify as base
from environment import choose as base_choose

base_execute = base.execute
choice_timing = None

HERE = Path(__file__).resolve().parent
base.s3a.HOST = "m1-n2a1-build"


def choose(observation, actions, defense_first):
    provisional = base_choose(observation, actions, defense_first)
    if provisional.choice is None:
        return provisional
    started = perf_counter_ns()
    variants = [a for a in actions if a.card == provisional.card and a.target == provisional.target]
    selected = min(variants, key=lambda a: (a.choice.upgrade, -a.choice.index))
    if choice_timing is not None:
        choice_timing.append(perf_counter_ns() - started)
    return selected


def execute(game, item, defense_first, phase):
    global choice_timing
    choice_timing = []
    try:
        row = base_execute(game, item, defense_first, phase)
        return row | {"choice_ms": sum(choice_timing) / 1e6, "choice_decisions": len(choice_timing)}
    finally:
        choice_timing = None


def original_stops():
    with gzip.open(HERE.parent / "m1-n2a/benchmark.json.gz", "rt", encoding="utf-8") as stream:
        original = json.load(stream)
    counts = Counter()
    for row in original["rows"]:
        if row["phase"] == "mixed" and row["terminal"]["status"] == "unsupported":
            step = row["trajectory"][-1]
            card = step["observation"]["hand"][step["action"]["args"]["card_index"]]
            counts[(row["id"], card["id"], row["terminal"]["result"]["boundary"])] += 1
    return [dict(id=key[0], card=key[1], boundary=key[2], count=count)
            for key, count in counts.items()]


def main():
    base.Episode = Episode
    base.choose = choose
    base.execute = execute
    base.main()


if __name__ == "__main__":
    main()
