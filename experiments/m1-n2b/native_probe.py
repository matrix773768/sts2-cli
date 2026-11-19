"""Replay one predetermined report root per encounter under each learned policy."""
import argparse
from pathlib import Path

from train import base, stamp, HERE
from analyze import read
from native_interaction import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("models", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = read(args.ledger)
    locked = read(args.models)
    digest = locked.pop("sha256")
    if stamp(locked) != digest or data["locked_model_sha256"] != digest:
        raise ValueError("Model lock differs")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    versions = base.s3a.solver_binding(args.output, base.s3a.FIXED, base.ROOT/"logs/m1-e3f/release")
    report = data["passes"][-1]
    roots = {r["id"]:r["root_sha256"] for r in report["lifecycle"]}
    items = read(HERE.parent/"m1-n2a2/manifest.json")["cases"]
    sentinels = {}
    for item in items:
        case = item["case"]
        if case["cohort"] == "report" and case["complexity"] == "mid_hp":
            sentinels.setdefault(case["spec"]["encounter"],item)
    results = dict(versions=versions, locked_sha256=digest, checks=[], lifecycle=[])
    for item in sentinels.values():
        root = item["case"]["id"]
        for model in locked["models"]:
            if "weights" not in model:
                continue
            row = next(r for r in report["rows"] if (r["id"],r["model"]) == (root,model["id"]))
            with base.worker(args.output,item|{"root_sha256":roots[root]},versions,results["lifecycle"]) as (game,surfaces):
                check = audit(game,surfaces["public_root"],row)
            results["checks"].append(dict(id=root,model=model["id"],**check))
            base.bank.atomic(args.output/"audit.json",results)


if __name__ == "__main__":
    main()
