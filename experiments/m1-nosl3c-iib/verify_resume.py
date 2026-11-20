"""Compare a resumed training ledger with an independently uninterrupted run."""
import argparse
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3

import torch


def equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, torch.Tensor):
        return torch.equal(left, right)
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def compare(resumed, uninterrupted):
    import gzip

    def read(path):
        with closing(sqlite3.connect(path / "training.sqlite")) as store:
            roots = {(phase, step, root): json.loads(gzip.decompress(raw))["rows"]
                     for phase, step, root, raw in store.execute("SELECT phase, step, root, rows FROM roots")}
            snapshots = {step: torch.load(io.BytesIO(raw), weights_only=True, map_location="cpu")
                         for step, raw in store.execute("SELECT step, payload FROM snapshots")}
        return roots, snapshots

    resumed_roots, resumed_models = read(resumed)
    expected_roots, expected_models = read(uninterrupted)
    assert resumed_roots == expected_roots and resumed_roots
    assert equal(resumed_models, expected_models) and max(resumed_models) > 0
    return dict(updates=max(resumed_models), roots=len(resumed_roots),
                public_trajectories_match=True, model_adam_and_rng_match=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resumed", type=Path)
    parser.add_argument("uninterrupted", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.resumed, args.uninterrupted), indent=2))
