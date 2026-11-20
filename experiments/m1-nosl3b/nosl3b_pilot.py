"""Measure all candidate recipes before the formal schedule is frozen."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from time import perf_counter

import torch

from nosl3b_protocol import HERE, PARTITIONS, digest, roots, validate
from nosl3b_episode import Arm, attempt, baseline
from nosl_experience import save_json
from nosl_model import Policy, checkpoint


def main(output):
    torch.set_num_threads(1)
    config = json.loads((HERE / "candidates.json").read_bytes())
    validate(config)
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit-only").mkdir()
    env = baseline.Prediction(output)
    policies = {}
    seeds = config["initialization_seeds"]
    for name, switches in baseline.ARMS.items():
        torch.manual_seed(seeds[0])
        policies[name] = Policy(*switches).eval()
    specs = [Arm(name, policy, digest(checkpoint(policy)), seeds[0], "sample")
             for name, policy in policies.items()]
    specs.extend([Arm("uniform", policies["mechanism"], None, None, "uniform"),
                  Arm("q1", None, None, None, "q1")])
    candidates = [r for split in PARTITIONS for r in roots(config, split, pilot=True)]
    rows = []
    tick = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = workers.map(lambda r: attempt(env, r, specs, config, "pilot"), candidates)
        for root, (episodes, audit) in zip(candidates, results, strict=True):
            save_json(output / "audit-only" / f"{root['id']}.json.gz", audit, compress=True)
            rows.extend(episodes)
    collection = perf_counter() - tick
    train_rows = [e for e in rows if e["recipe_split"] == "train"]
    updates = {}
    for name, policy in policies.items():
        optimizer = torch.optim.Adam(policy.parameters(), lr=config["learning_rate"])
        updates[name] = baseline.train(policy, optimizer, [e for e in train_rows if e["arm"] == name], config)
    save_json(output / "pilot.json.gz", rows, compress=True)
    summary = dict(config_sha256=digest(config), engine=env.versions, collection_seconds=collection,
                   by_arm={arm.name: baseline.summarize([e for e in rows if e["arm"] == arm.name])
                           for arm in specs}, updates=updates,
                   candidates=[dict(root=r["id"], family=r["family"], split=r["recipe_split"],
                                    pressure=r["pressure"], stocked=r["stocked"],
                                    statuses={e["arm"]: e["feedback"]["status"] for e in rows if e["root"] == r["id"]})
                               for r in candidates])
    save_json(output / "summary.json", summary)
    print({arm: stats["statuses"] for arm, stats in summary["by_arm"].items()}, flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
