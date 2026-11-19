"""Generate a D1 native-history campaign from the discovered player roster."""
import argparse
from pathlib import Path

from space import digest, read
from engine import bank


def plan(catalog, namespace, runs_per_character, roots_per_run):
    runs = []
    for char in catalog["characters"]:
        for i in range(runs_per_character):
            retry = 0
            while True:
                token = digest([namespace, char["name"], i, retry])
                seed = "LSH" + token[:10].upper()
                run = dict(id=token[:16], character=char["name"], seed=seed,
                           ascension=(0, 2, 5)[i % 3], map="random", reward="first", shop="leave")
                if bank.lineage(run)[1] == "development":
                    break
                retry += 1
            runs.append(run)
    return dict(limits=dict(run_seconds=55, batch_seconds=320, audit_seconds=16, combat_seconds=18,
                            run_actions=220, combat_actions=100, roots_per_run=roots_per_run,
                            max_runs=len(runs), disk_mib=150, min_act=1),
                defaults=dict(character=catalog["characters"][0]["name"], ascension=0, map="random",
                              reward="first", shop="leave"), runs=runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--runs-per-character", type=int, default=3, choices=range(1, 5))
    parser.add_argument("--roots-per-run", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("History plan already exists")
    bank.atomic(args.output, plan(read(args.catalog), args.namespace, args.runs_per_character, args.roots_per_run))
