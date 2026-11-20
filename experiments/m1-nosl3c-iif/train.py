"""Run the unchanged v4 objective with versioned IIF admission."""
import argparse
from collections import Counter
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
from types import FunctionType

import torch

from audit import HERE, VERSION, certify, targets
from objective import Objective
from nosl_experience import save_json
from training import MODEL, Policy, checkpoint_policy, optimize
import runpy

schedule = runpy.run_path(str(HERE.parent / "m1-nosl3c-iie/run.py"))["schedule"]

runner = targets.run_admission


def run(output, solver, config, mode, through):
    Objective(**config["objective"])
    if config["microbatch"] < 1:
        raise ValueError("Expected positive microbatch")
    targets.configure()
    config = config | dict(batches=schedule(output, solver, config),
        certification=dict(mode=mode, rule=VERSION), model=MODEL,
        sources={f"{p.parent.name}/{p.name}": sha256(p.read_bytes()).hexdigest()
                 for directory in (HERE, HERE.parent / "m1-nosl3c-iie")
                 for p in sorted(directory.glob("*.py"))})
    entry = targets.train_interactive.collect.__wrapped__
    collect = torch.no_grad()(FunctionType(entry.__code__, entry.__globals__ |
                    dict(project=targets.project, Decision=targets.Decision, MODEL=MODEL)))
    base_attempt = FunctionType(runner.attempt.__code__, runner.attempt.__globals__ |
                               dict(collect=collect, certify=partial(certify, mode=mode)))

    def attempt(*args):
        result = base_attempt(*args)
        proof = result["evidence"]
        for row in result["rows"]:
            row["qualification"] = {k: proof.get(k) for k in ("certification", "rule", "route", "mode")}
            if row["feedback"]["eligible"] and proof["certification"] == "semantic_native_match":
                row["feedback"]["evidence"] = "semantic_native_route"
        return result

    def update(policy, adam, rows, cfg, model_sha):
        accepted = []
        for row in rows:
            qualification = row["qualification"]
            if qualification["mode"] != mode or not qualification["route"]:
                raise ValueError("Wrong admission lineage")
            if qualification["certification"] == "semantic_native_match" and mode == "semantic":
                if qualification["rule"] != VERSION or row["feedback"]["evidence"] != "semantic_native_route":
                    raise ValueError("Unknown semantic rule")
                # The frozen optimizer uses this label as an admission guard.
                # Translate only in-memory after validating the new provenance.
                row = row | {"feedback": row["feedback"] | {"evidence": "exact_native_route"}}
            elif qualification["certification"] != "exact_native_match":
                raise ValueError("Unverified feedback in optimization batch")
            accepted.append(row)
        return optimize(policy, adam, accepted, cfg, model_sha)

    def report(output, cases, step, elapsed, stats):
        runner.summarize(output, cases, step, elapsed, stats)
        classifications = Counter(
            row["qualification"].get("certification") or case["status"]
            for case in cases for row in case["rows"])
        classifications.update(case["status"] for case in cases if not case["rows"])
        path = output / "report.json"
        summary = json.loads(path.read_bytes()) | dict(
            certification=dict(mode=mode, rule=VERSION, counts=classifications))
        save_json(path, summary)
        with (output / "report.md").open("a", encoding="utf-8") as markdown:
            markdown.write("\n")
            markdown.writelines(f"- {kind} {count}\n" for kind, count in sorted(classifications.items()))

    original = runner.run
    execute = FunctionType(original.__code__, original.__globals__ | dict(
        attempt=attempt, optimize=update, Policy=Policy, checkpoint_policy=checkpoint_policy, summarize=report))
    execute(output, solver, config, config["workers"], len(config["batches"]) if through is None else through)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("exact", "semantic", "diagnostic"), default="exact")
    parser.add_argument("--through-update", type=int)
    a = parser.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    run(a.output.resolve(), a.solver.resolve(), json.loads(a.config.read_bytes()), a.mode, a.through_update)
