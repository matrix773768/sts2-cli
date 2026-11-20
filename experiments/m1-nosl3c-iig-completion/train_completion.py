"""Validate the completion engine using the frozen v4 policy and optimizer."""
import argparse
import json
from pathlib import Path
import runpy
from types import FunctionType

import torch

from completion_engine import HERE, RULE, bind, certify, targets
from replay_archive import read_matrix
from nosl_experience import save_json

IIG = HERE.parent / "m1-nosl3c-iig"
TRAIN = runpy.run_path(str(HERE.parent / "m1-nosl3c-iif/train.py"))["run"]


def configuration(kind, output):
    if kind == "integration":
        return json.loads((IIG / "integration.json").read_bytes())
    config = json.loads((IIG / "independent.json").read_bytes())
    if kind == "holdout":
        source, = config["stages"]
        distribution = source["distribution"]
        config["stages"] = [
            source | {"distribution": distribution | dict(seed=878129, count=30, hp=None, max_hp=None)},
            source | {"distribution": distribution | dict(seed=971093, count=30)},
        ]
    if kind == "resample":
        # The original matrix is held fixed. Each row here is a separately labelled
        # new policy trajectory on the same root, including the old worker failure.
        categories = {"incomplete_archived_route", "engine_failure",
                      "checkpoint_unavailable", "visibility_unverified"}
        sources = [dict(ledger=ledger, step=row["step"], position=row["position"],
                        category=row["category"], spec=row["spec"])
                   for ledger, rows in read_matrix().items() for row in rows
                   if row["category"] in categories]
        save_json(output / "resampling-roots.json", sources)
        del config["stages"]
        config["batches"] = [[row["spec"] for row in sources]]
    return config


def run(output, solver, config, mode, through):
    targets.worker_bind = bind
    entry = FunctionType(TRAIN.__code__, TRAIN.__globals__ | dict(HERE=HERE, VERSION=RULE, certify=certify))
    entry(output, solver, config, mode, through)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--suite", choices=("integration", "pair16", "holdout", "resample"), required=True)
    parser.add_argument("--mode", choices=("exact", "semantic", "diagnostic"), default="exact")
    parser.add_argument("--through-update", type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    run(output, args.solver.resolve(), configuration(args.suite, output), args.mode, args.through_update)
