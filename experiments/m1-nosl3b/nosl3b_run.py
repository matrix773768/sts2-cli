"""Resumable train/evaluate runner for the frozen NOSL3B protocol."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import torch

from nosl3b_protocol import HERE, digest, roots, validate
from nosl3b_episode import Arm, attempt, baseline
from nosl3b_store import Store, restore, snapshot, tensor_bytes
from nosl_experience import json_bytes, save_json, targets
from nosl_model import Policy


def initialize(config):
    models, optimizers = {}, {}
    for seed in config["initialization_seeds"]:
        for arm, switches in baseline.ARMS.items():
            torch.manual_seed(seed)
            key = f"{seed}:{arm}"
            models[key] = Policy(*switches).eval()
            optimizers[key] = torch.optim.Adam(models[key].parameters(), lr=config["learning_rate"])
    return models, optimizers


def arms(models, state, modes, stage):
    for key, policy in models.items():
        seed, name = key.split(":")
        for mode, repeat in modes:
            yield Arm(name, policy, state[key]["model_hash"], int(seed), mode, repeat, stage)


def collect(store, env, config, phase, step, candidates, make_specs, workers):
    begun = perf_counter()
    processed = store.done(phase, step)
    selected = [root for root in candidates if root["id"] not in processed]

    def run(root):
        tick = perf_counter()
        episodes, audit = attempt(env, root, make_specs(root), config, step)
        return episodes, audit, perf_counter() - tick

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for root, (episodes, audit, elapsed) in zip(selected, pool.map(run, selected), strict=True):
            save_json(env.output / "audit-only" / f"{phase}-{step}-{root['id']}.json.gz",
                      audit, compress=True)
            store.append(phase, step, root["id"], episodes, elapsed)
    return perf_counter() - begun


def fit(store, env, config, stop, workers):
    previous = store.latest()
    if previous is None:
        models, optimizers = initialize(config)
        store.save(0, snapshot(models, optimizers), {})
        previous = 0
    while previous < stop:
        state, _ = store.load(previous)
        models, optimizers = restore(state, config, resume=True)
        specs = list(arms(models, state, [("sample", 0)], previous))
        stage_roots = list(roots(config, "train", previous))
        collect_seconds = collect(store, env, config, "train", previous, stage_roots, lambda _: specs, workers)
        episodes = list(store.rows("train", previous))
        updates = {}
        start = perf_counter()
        for arm in specs:
            key = f"{arm.initialization}:{arm.name}"
            batch = [e for e in episodes if (e["arm"], e["initialization"]) == (arm.name, arm.initialization)]
            if len(batch) != len(stage_roots) or any(e["behavior"]["model_sha256"] != arm.model_hash for e in batch):
                raise ValueError(f"On-policy lineage mismatch for {key}")
            tick = perf_counter()
            updates[key] = baseline.train(models[key], optimizers[key], batch, config)
            updates[key]["seconds"] = perf_counter() - tick
        elapsed = perf_counter() - start
        previous += 1
        store.save(previous, snapshot(models, optimizers),
                   dict(collect_seconds=collect_seconds, optimizer_seconds=elapsed, updates=updates))
        print(f"update {previous} qualified", {k: v["qualified"] for k, v in updates.items()}, flush=True)


def evaluate(store, env, config, workers):
    stages = config["schedule"]["checkpoints"]
    specs = []
    modes = [("sample", j) for j in range(config["sample_replicates"])] + [("greedy", 0)]
    for stage in stages:
        state, _ = store.load(stage)
        models, _ = restore(state, config, resume=False)
        specs.extend(arms(models, state, modes, stage))
    specs.append(Arm("q1", None, None, None, "q1", stage="reference"))
    report = [r for split in ("regular", "combination") for r in roots(config, split)]
    elapsed = collect(store, env, config, "report", -1, report, lambda _: specs, workers)
    print(f"report collection {elapsed:.2f}s", flush=True)
    audit_specs = [arm for arm in specs if arm.stage == stages[-1] and arm.name == "mechanism"
                   and arm.mode == "sample" and arm.replicate == 0]
    interventions = [Arm(a.name, a.model, a.model_hash, a.initialization, "without_potion",
                         stage=a.stage) for a in audit_specs]
    elapsed_audit = collect(store, env, config, "counterfactual", -1, [r for r in report if r["stocked"]],
                            lambda _: interventions, workers)
    print(f"audit collection {elapsed_audit:.2f}s", flush=True)
    return dict(report_seconds=elapsed, counterfactual_seconds=elapsed_audit)


def export(store, output, config, identity):
    last = store.latest()
    checkpoints = []
    for step in config["schedule"]["checkpoints"]:
        if step > last:
            continue
        state, _ = store.load(step)
        path = output / f"policy-u{step:02d}.pt"
        # Tensor-only PyTorch snapshots can be restored with weights_only=True.
        weights = {key: {k: v for k, v in entry.items() if k != "optimizer"} for key, entry in state.items()}
        raw = tensor_bytes(dict(step=step, identity=identity, models=weights))
        path.write_bytes(raw)
        checkpoints.append(dict(update=step, file=path.name, file_sha256=sha256(raw).hexdigest(),
                                models={key: value["model_hash"] for key, value in weights.items()}))
    state, _ = store.load(last)
    raw = tensor_bytes(dict(step=last, identity=identity, models=state))
    (output / "resume-latest.pt").write_bytes(raw)
    ledger_path = output / "public.jsonl.gz"
    manifest = sha256()
    n = 0
    with ledger_path.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
        for phase in ("train", "report"):
            for record in store.rows(phase):
                line = json_bytes(record) + b"\n"
                manifest.update(line)
                archive.write(line)
                n += 1
    save_json(output / "manifest.json", dict(identity=identity, checkpoints=checkpoints,
              optimizer_snapshot=dict(step=last, sha256=sha256(raw).hexdigest()),
              ledger=dict(rows=n, uncompressed_sha256=manifest.hexdigest()),
              source_note="Public episodes omit exact roots, hidden RNG, private replay and interventions."))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "formal.json")
    parser.add_argument("--through-update", type=int, help="Stop after durable checkpoint, before report evaluation")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    config = json.loads(args.config.read_bytes())
    validate(config)
    last = config["schedule"]["updates"]
    stop = last if args.through_update is None else args.through_update
    if not 0 <= stop <= last:
        parser.error("Checkpoint is outside the frozen schedule")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit-only").mkdir(exist_ok=True)
    env = baseline.Prediction(output)
    source = {p.name: digest(p.read_text(encoding="utf-8")) for p in
              sorted([*HERE.glob("nosl3b_*.py"), HERE.parent / "m1-nosl3a/nosl_model.py",
                      HERE.parent / "m1-nosl3a/nosl_run.py"])}
    identity = dict(protocol=digest(config), engine=env.versions, workers=args.workers, source=source)
    with env.b1b.bank.writer(output), closing(Store(output / "training.sqlite", identity)) as store:
        fit(store, env, config, stop, args.workers)
        clock_path = output / "last-evaluation-clock.json"
        if args.through_update is None and not clock_path.exists():
            timing = evaluate(store, env, config, args.workers)
            save_json(clock_path, timing)
        export(store, output, config, identity)


if __name__ == "__main__":
    main()
