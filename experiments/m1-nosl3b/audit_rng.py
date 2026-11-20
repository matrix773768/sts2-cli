"""Probe game RNG independently of model, recipe, resources and policy seed."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import torch

from nosl3b_protocol import HERE, digest, roots
from nosl3b_episode import attempt, baseline
from nosl3b_store import restore, tensors, unpack
from nosl3b_run import arms
from nosl_experience import save_json
from analyze import path


def main(output, config):
    torch.set_num_threads(1)
    last = config["schedule"]["updates"]
    with sqlite3.connect(output / "training.sqlite") as db:
        originals = [r for payload, in db.execute("SELECT rows FROM roots WHERE phase='report'") for r in unpack(payload)]
        original = {(r["root"], r["initialization"], r["replicate"]): r for r in originals
                    if r["mode"] == "sample" and r["arm"] == "mechanism" and r["iteration"] == last}
    saved = tensors((output / "resume-latest.pt").read_bytes())
    if saved["step"] != last or saved["identity"]["protocol"] != digest(config):
        raise ValueError("Incompatible final checkpoint")
    state = {k: v for k, v in saved["models"].items() if k.endswith(":mechanism")}
    models, _ = restore(state, config, resume=False)
    specs = list(arms(models, state, [("sample", i) for i in range(config["sample_replicates"])], last))

    # Select the first two recipes per report partition and their first root, independent of outcomes.
    candidates = [r for split in ("regular", "combination")
                  for r in list(roots(config, split))[::config["report_reps_per_family"]][:2]]
    env = baseline.Prediction(output)

    def compare_root(root):
        variant = deepcopy(root)
        # Keep the opaque root ID to replay the exact policy-sampling streams.
        variant["spec"]["seed"] = digest([root["spec"]["seed"], "nosl3b-audit-rng-v1"])[:12].upper()
        if variant["spec"]["seed"] == root["spec"]["seed"]:
            raise ValueError("Game RNG intervention did not change seed")
        return attempt(env, variant, specs, config, "audit_rng")

    counts = Counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for root, (rows, audit) in zip(candidates, pool.map(compare_root, candidates), strict=True):
            save_json(output / "audit-only" / f"rng-{root['id']}.json.gz", dict(rows=rows, audit=audit), compress=True)
            for row in rows:
                reference = original[(root["id"], row["initialization"], row["replicate"])]
                assert reference["behavior"]["seed"] == row["behavior"]["seed"]
                counts["pairs"] += 1
                counts["different_paths"] += int(path(reference) != path(row))
                counts["different_outcomes"] += int(reference["feedback"]["status"] != row["feedback"]["status"])
                counts["different_initial_public_states"] += int(
                    [s["observation"] for s in reference["transitions"][:1]] !=
                    [s["observation"] for s in row["transitions"][:1]])
    save_json(output / "rng-summary.json", dict(roots=len(candidates), **counts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "formal.json")
    args = parser.parse_args()
    main(args.output.resolve(), json.loads(args.config.read_bytes()))
