"""Paired cold/resident, feature-cache and scheduling performance qualification."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

import torch

from protocol import HERE, digest, read, root
from worker import Environment, Worker
from nosl_experience import save_json
from nosl_model import Policy, checkpoint
from nosl_run import quantiles


def semantic(batch, audit):
    rows = [{k: r[k] for k in ("root", "mode", "behavior", "transitions", "feedback")} for r in batch["rows"]]
    return digest([rows, audit["exact_root_sha256"], audit["traces"]])


def measure(env, config, policy, items, resident, cache, workers, baseline):
    model_hash = digest(checkpoint(policy))
    modes = [("sample", i) for i in range(config["traces_per_root"])]

    def run(lane):
        records = []
        with closing(Worker(env, config, resident=resident, cache=cache)) as worker:
            for index, item in lane:
                batch, audit = worker.attempt(item, 0, model_hash, policy, modes)
                records.append((index, dict(id=item["id"], timing=batch["timing"],
                                            scores=[r["timing"] for r in batch["rows"]],
                                            results=[r["feedback"]["status"] for r in batch["rows"]],
                                            stamp=semantic(batch, audit))))
        return records

    started = perf_counter()
    indexed = list(enumerate(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = sorted(pair for lane in pool.map(run, [indexed[i::workers] for i in range(workers)]) for pair in lane)
    seconds = perf_counter() - started
    evidence = [r for _, r in records]
    for row in evidence:
        if baseline.setdefault(row["id"], row["stamp"]) != row["stamp"]:
            raise ValueError(f"Cold/warm prediction or hidden-state divergence at {row['id']}")
    phases = {k: quantiles([r["timing"][k] for r in evidence]) for k in
              ("startup_ms", "handshake_ms", "initialize_ms", "snapshot_ms", "total_ms")}
    phases["model_init_ms"] = quantiles([r["timing"]["build_phases"].get("model_init", 0) for r in evidence])
    phases["retirement_ms"] = quantiles([r["timing"]["retirement_ms"] for r in evidence if "retirement_ms" in r["timing"]])
    phases["hot_rollout_phases"] = {field: quantiles([r[field] for e in evidence for r in e["scores"]])
                                    for field in evidence[0]["scores"][0]}
    phases["warm_initialize_ms"] = quantiles([r["timing"]["initialize_ms"] for r in evidence if r["timing"]["resident"]])
    phases["warm_roots"] = sum(r["timing"]["resident"] for r in evidence)
    phases["cache_hits"] = sum(r["timing"]["cache_hits"] for r in evidence)
    labels = Counter(s for r in evidence for s in r["results"])
    n = sum(labels.values())
    return dict(resident=resident, cache=cache, workers=workers, root_attempts=len(items),
                independent_roots=len({r["id"] for r in items}), attempts=n, labels=labels,
                wall_s=seconds, attempts_per_s=n / seconds,
                retirement=Counter(r["timing"]["retirement"] for r in evidence), phases=phases, roots=evidence)


def main(output, config):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(config["initialization_seed"])
    model = Policy(True, True).eval()
    (output / 'audit-only').mkdir(parents=True, exist_ok=False)
    env = Environment(output)
    distinct = [root(config, "bench", i) for i in range(12)]
    # Same-root A/B/A, plus diverse roles, encounters and pressure bands.
    items = [distinct[0], distinct[1], distinct[0], *distinct[2:]]
    reference, measures = {}, {}
    for name, resident, cache, workers in (("cold_uncached", False, False, 1),
                                             ("cold_cached", False, True, 1),
                                             ("resident_cached", True, True, 1),
                                             ("resident_two", True, True, 2),
                                             ("resident_four", True, True, 4)):
        measures[name] = measure(env, config, model, items, resident, cache, workers, reference)
        save_json(output / "benchmark.json", dict(protocol=digest(config), environment=env.versions,
                                                   semantic_equal=True, measures=measures))
        print(name, measures[name]["labels"], measures[name]["attempts_per_s"],
              measures[name]["retirement"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "pilot.json")
    args = p.parse_args()
    main(args.output.resolve(), read(args.config))