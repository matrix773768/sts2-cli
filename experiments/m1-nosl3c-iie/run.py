"""Run bounded or ongoing staged training with the strict v4 objective."""
import argparse
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from types import FunctionType

import torch

from terminal_contract import HERE, VERSION, certify, targets
from objective import Objective
from training import MODEL, Policy, checkpoint_policy, optimize
from nosl_experience import digest, save_json, terminal
from resident import Auditors

runner = targets.run_admission


def schedule(output, solver, config):
    if "stages" not in config:
        return config["batches"]
    versions = targets.worker_bind(output, solver)
    with ExitStack() as stack:
        native = targets.open_worker(output, stack, versions).request("synthetic_catalog")
    groups, manifest = [], []
    for stage_index, stage in enumerate(config["stages"]):
        catalog = native | dict(
            characters=[c for c in native["characters"] if c["name"] in stage["characters"]],
            acts=[a for a in native["acts"] if a["act"] in stage["acts"]])
        if stage.get("card_ids"):
            catalog["characters"] = [c | {"cards": [card for card in c["cards"]
                                         if card["id"] in stage["card_ids"]]}
                                     for c in catalog["characters"]]
        if (not catalog["characters"] or not catalog["acts"]
                or any(not c["cards"] for c in catalog["characters"])):
            raise ValueError("Empty course stage")
        for batch in range(stage["updates"]):
            distribution = dict(stage["distribution"])
            distribution["seed"] = digest([distribution["seed"], stage_index, batch])
            generated = list(runner.generate(catalog, **distribution))
            manifest.append(generated)
            groups.append([r["spec"] for r in generated for _ in range(stage["trajectories_per_root"])])
    save_json(output / "course-roots.json", manifest)
    return groups


def run(output, solver, config, workers, through):
    Objective(**config["objective"])
    if config["microbatch"] < 1 or config.get("audit_mode") != "strict":
        raise ValueError("Require positive microbatch and exact native audit")
    targets.configure()
    config = config | {"batches": schedule(output, solver, config), "terminal_contract": VERSION,
                       "model": MODEL, "iie_sources": {
        p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))}}
    original_collect = targets.train_interactive.collect.__wrapped__
    collector = torch.no_grad()(FunctionType(original_collect.__code__,
        original_collect.__globals__ | dict(project=targets.project, Decision=targets.Decision, MODEL=MODEL)))
    auditors = Auditors(config.get("resident_auditor_limit", 0))

    def accounting_feedback(state, last_action):
        feedback = terminal(state, last_action)
        raw = state.get("result") or {}
        feedback["engine_accounting"] = {"cumulative_loss": raw.get("cumulative_loss")}
        return feedback

    def certificate(output, versions, spec, row):
        evidence = certify(output, versions, spec, row, auditors.audit)
        # Store only aggregate certification metadata in the public journal.
        return evidence

    attempt = FunctionType(runner.attempt.__code__, runner.attempt.__globals__ |
                           dict(collect=collector, certify=certificate, terminal=accounting_feedback))

    def update(policy, adam, rows, cfg, model_hash):
        start = perf_counter()
        result = optimize(policy, adam, rows, cfg, model_hash)
        return result | {"seconds": perf_counter() - start}

    def report(output, cases, step, elapsed, stats):
        runner.summarize(output, cases, step, elapsed, stats)
        path = output / "report.json"
        result = json.loads(path.read_bytes())
        result["by_max_hp"] = {}
        decisions = 0
        for case in cases:
            band = result["by_max_hp"].setdefault(str(case["spec"]["max_hp"]), Counter())
            band["attempted"] += 1
            band[case["status"]] += 1
            for row in case["rows"]:
                band["prediction_" + row["feedback"]["status"]] += 1
                decisions += len(row["transitions"])
        result.update(decisions=decisions, decisions_per_second=decisions/elapsed,
                      complete_per_second=result["completed"]/elapsed,
                      strict_per_second=sum(s.startswith("admissible_") for s in
                                            (c["status"] for c in cases))/elapsed,
                      cold_roots=len(cases), hot_roots=0)
        audit_metrics = [json.loads((output/"audit"/f"{step-1:06d}-{case['root']}.json").read_bytes())
                         for case in cases]
        result["resident_audits"] = sum(m.get("auditor_reused", False) for m in audit_metrics)
        result["retirements"] = Counter(m["retirement"] for m in audit_metrics if "retirement" in m)
        save_json(path, result)
        save_json(output / f"update-{step:06d}.json", result)

    execute = FunctionType(runner.run.__code__, runner.run.__globals__ | dict(
        attempt=attempt, optimize=update, Policy=Policy, checkpoint_policy=checkpoint_policy, summarize=report))
    try:
        execute(output, solver, config, workers, len(config["batches"]) if through is None else through)
    finally:
        auditors.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--through-update", type=int)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    run(args.output.resolve(), args.solver.resolve(), cfg,
        args.workers if args.workers is not None else cfg["workers"], args.through_update)
