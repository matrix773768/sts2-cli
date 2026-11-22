"""Bounded III-A1 training and strictly audited paired evaluation."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
from time import perf_counter
from types import FunctionType, SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
p0 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii-p0/run.py"))
v4, torch, save, digest = (p0[k] for k in ("v4", "torch", "save", "digest"))
targets, runner, solver = p0["targets"], p0["runner"], p0["SOLVER"]
TRAIN_ROOT_SEED = 73192101
EVAL_ROOT_SEED = 73192102
TRAIN_POLICY_SEED = 43192101
EVAL_POLICY_SEED = 43192102


def read(path):
    return json.loads(path.read_bytes())


def readonly(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


def freeze(out, cfg):
    train, evaluation = out / "train-manifest", out / "eval-manifest"
    train.mkdir()
    evaluation.mkdir()
    eval_cfg = read_copy(cfg)
    stage = eval_cfg["stages"][0]
    stage["updates"] = 1
    stage["distribution"].update(seed=EVAL_ROOT_SEED, count=48)
    batches = v4.schedule(train, solver, cfg)
    eval_roots, = v4.schedule(evaluation, solver, eval_cfg)
    all_roots = [root for batch in batches for root in batch] + eval_roots
    seeds = {root["seed"] for root in all_roots}
    assert len(batches) == 12 and all(len(batch) == 24 for batch in batches)
    assert len(eval_roots) == 48 and len(seeds) == 336
    assert all(root["hp"] == root["max_hp"] == 999 for root in all_roots)
    old, = read(Path("logs/nosl3c-iii-p0-01/catalog/course-roots.json"))
    assert not seeds.intersection(item["spec"]["seed"] for item in old)
    checked = {}
    for name in ("iik5-pair16", "iik5-holdout", "nosl3c-iic-random-final",
                 "nosl3c-iid-release-independent", "nosl3c-iie-broad"):
        file = Path("logs") / name / "training.sqlite"
        with readonly(file) as db:
            old_seeds = {p0["unpack"](raw)["spec"]["seed"] for raw, in
                         db.execute("SELECT rows FROM roots WHERE phase='train'")}
        assert not seeds & old_seeds
        checked[name] = len(old_seeds)
    eval_seeds = [int(digest([EVAL_POLICY_SEED, idx])[:16], 16) for idx in range(48)]
    save(out / "protocol.json", dict(config=cfg, train_sha256=digest(batches), eval_sha256=digest(eval_roots),
                                     excluded_ledgers=checked, evaluation_policy_seeds=eval_seeds))
    return batches, eval_roots, eval_seeds


def read_copy(value):
    return json.loads(json.dumps(value))


def train(out, cfg, batches, meter, events):
    journal = runner.Journal
    optimize = v4.optimize
    summarize = runner.summarize
    start = meter.start_phase()
    first_worker = len(events)
    timing = {}
    consecutive_failures = 0
    commit_root = journal.commit_root

    def root_commit(self, phase, step, batch):
        nonlocal consecutive_failures
        commit_root(self, phase, step, batch)
        failed = batch["status"] in {"engine_failure", "root_failure", "audit_failure"}
        consecutive_failures = consecutive_failures + 1 if failed else 0
        if consecutive_failures >= 4:
            (out / "STOP").touch()

    def update(policy, adam, rows, settings, model_hash):
        tick = perf_counter()
        result = optimize(policy, adam, rows, settings, model_hash)
        timing["optimizer_s"] = perf_counter() - tick
        objective = v4.Objective(**settings["objective"])
        advantages = torch.tensor([
            objective.reward(row["feedback"], row["hp_accounting"]["initial_hp"]) - step["value"]
            for row in rows for step in row["transitions"]
        ], dtype=torch.float64)
        timing["advantages"] = dict(mean=advantages.mean().item(), sd=advantages.std(unbiased=False).item(),
                                    min=advantages.min().item(), max=advantages.max().item())
        timing["trained_rows"] = len(rows)
        timing["trained_transitions"] = len(advantages)
        return result

    def report(output, cases, step, elapsed, stats):
        assert stats, f"Update {step}: no qualified training trajectories"
        timing["collection_s"] = elapsed - stats["seconds"]
        timing["audit_worker_s"] = sum(case["timing"].get("audit_ms", 0) for case in cases) / 1000
        timing["statuses"] = Counter(case["status"] for case in cases)
        summarize(output, cases, step, elapsed, stats)

    original_save = journal.save

    def checkpoint(self, step, payload, stats):
        nonlocal start, first_worker
        tick = perf_counter()
        original_save(self, step, payload, stats)
        if step:
            save(out / f"metrics-{step:02d}.json",
                 timing | dict(sqlite_s=perf_counter()-tick, resources=meter.end_phase(start),
                               host_starts=len(events)-first_worker, stats=stats))
            print(f"Committed update {step}: {stats['qualified']}/24 trajectories", flush=True)
            timing.clear()
        start = meter.start_phase()
        first_worker = len(events)

    frozen = {k: v for k, v in cfg.items() if k != "stages"} | {"batches": batches}
    with patch.object(journal, "save", checkpoint), patch.object(journal, "commit_root", root_commit), \
            patch.object(v4, "optimize", update), patch.object(runner, "summarize", report):
        v4.run(out, solver, frozen, cfg["workers"], 12)


class Greedy:
    def __init__(self, _seed):
        pass

    def choices(self, population, *, weights, k):
        assert k == 1
        return [max(population, key=weights.__getitem__)]


def evaluate(out, cfg, roots, seeds, policy, mode):
    out.mkdir()
    versions = targets.worker_bind(out, solver)
    model_hash = digest(v4.checkpoint_policy(policy))
    original = targets.train_interactive.collect.__wrapped__

    def feedback(state, action):
        return v4.terminal(state, action) | {
            "engine_accounting": {"cumulative_loss": (state.get("result") or {}).get("cumulative_loss")}
        }

    deps = original.__globals__ | dict(project=targets.project, Decision=targets.Decision,
                                      MODEL=v4.MODEL, terminal=feedback)
    if mode == "greedy":
        deps["random"] = SimpleNamespace(Random=Greedy)
    collect = torch.no_grad()(FunctionType(original.__code__, deps))
    auditors = v4.Auditors(cfg["resident_auditor_limit"])

    def certify(output, identity, root, row):
        return v4.certify(output, identity, root, row, auditors.audit)

    raw_attempt = runner.attempt
    attempt = FunctionType(raw_attempt.__code__, raw_attempt.__globals__ |
                           dict(collect=collect, certify=certify, terminal=feedback))

    def one(entry):
        index, (root, seed) = entry
        result = attempt(out, versions, root, policy, model_hash, seed, cfg["action_cap"])
        for row in result["rows"]:
            row.update(split="development-evaluation", mode=mode)
        result.update(root_index=index, seed=seed, spec=root, model_sha256=model_hash)
        save(out / f"root-{index:03d}.json", result)
        return result["status"]

    try:
        from concurrent.futures import ThreadPoolExecutor
        statuses = []
        with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
            for start in range(0, len(roots), cfg["workers"]):
                statuses.extend(pool.map(one, list(enumerate(zip(roots, seeds, strict=True)))[start:start+cfg["workers"]]))
                if all(s in {"engine_failure", "root_failure", "audit_failure"} for s in statuses[-cfg["workers"]:]):
                    raise RuntimeError("Persistent evaluation host failures")
    finally:
        auditors.close()
    return Counter(statuses)


def checkpoints(path):
    with readonly(path) as db:
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        rows = list(db.execute("SELECT step,payload,sha FROM snapshots ORDER BY step"))
        assert [step for step, _, _ in rows] == list(range(13))
        for step, raw, stamp in rows:
            assert sha256(raw).hexdigest() == stamp
            if step in (0, 4, 8, 12):
                state = p0["tensors"](raw)
                policy = v4.Policy().eval()
                policy.load_state_dict(state["model"])
                assert digest(v4.checkpoint_policy(policy)) == state["model_sha256"]
                assert step == 0 or state["adam"]["state"]
                assert isinstance(state["rng"], torch.Tensor)
                yield step, policy, stamp


def main(output):
    output.mkdir(parents=True)
    cfg = p0["config"]()
    cfg.update(workers=4, policy_seed=TRAIN_POLICY_SEED)
    cfg["stages"][0]["updates"] = 12
    cfg["stages"][0]["distribution"]["seed"] = TRAIN_ROOT_SEED
    p0["verify_main"]()
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    targets.worker_bind = p0["accept"]["bind"]
    targets.configure()
    events = []
    with p0["Meter"]() as meter, p0["observe_workers"](meter, events):
        try:
            batches, roots, seeds = freeze(output, cfg)
            training = output / "training"
            training.mkdir()
            train(training, cfg, batches, meter, events)
            saved = list(checkpoints(training / "training.sqlite"))
            save(output / "checkpoints.json", {step: stamp for step, _, stamp in saved})
            for step, policy, _ in saved:
                if step in (0, 12):
                    for mode in ("sample", "greedy"):
                        name = f"eval-{step:02d}-{mode}"
                        first = len(events)
                        tick = meter.start_phase()
                        statuses = evaluate(output / name, cfg, roots, seeds, policy, mode)
                        save(output / name / "summary.json", dict(statuses=statuses, resources=meter.end_phase(tick),
                                                                 host_starts=len(events)-first))
                        print(name, dict(statuses), flush=True)
        finally:
            save(output / "workers.json", events)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
