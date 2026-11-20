"""Bounded NOSL3C-Ib performance runner using the frozen journal and native worker."""
import argparse
from collections import Counter
from functools import wraps
from inspect import getsource
from pathlib import Path
import runpy
import signal
from threading import local
from time import perf_counter, time_ns
import traceback
from unittest.mock import patch

import torch

from features import BASE, FastDecision, protocol
import optimizer
import profile_stock
from resources import Meter
import worker
from nosl_experience import json_bytes, save_json
from nosl_run import quantiles

HERE = Path(__file__).resolve().parent


class FastCache(worker.DecisionCache):
    def get(self, obs):
        if not self.capacity:
            return FastDecision(obs)
        key = json_bytes(obs)
        if key in self.rows:
            self.hits += 1
            return self.rows[key]
        result = FastDecision(obs)
        if len(self.rows) < self.capacity:
            self.rows[key] = result
        return result


class Profile:
    def __init__(self, path, meter):
        self.path, self.meter = path, meter
        self.events = []
        self.io = Counter()

    def record(self, name, data):
        self.events.append(dict(event=name, **data))

    def wrap(self, name, function):
        @wraps(function)
        def measured(*args, **kwargs):
            tick = self.meter.snapshot()
            try:
                return function(*args, **kwargs)
            finally:
                self.record(name, self.meter.end_phase(tick))
        return measured

    def save(self):
        save_json(self.path, dict(logical_cpus=self.meter.cores, peak_rss_mb=self.meter.peak/2**20
                                  if self.meter.kernel else None, events=self.events))


def install(scope, profile, args):
    reference_fleet = scope["Fleet"]
    reference_rollout = worker.rollout
    reference_collect = scope["collect"]
    history = local()

    class MeasuredPolicy:
        def __init__(self, policy):
            self.policy = policy

        def __call__(self, *args):
            return self.policy(*args)

        def remember(self, *args):
            tick = perf_counter()
            result = self.policy.remember(*args)
            history.ms += (perf_counter() - tick) * 1000
            return result

    def rollout(game, cfg, row, policy, cache, trace):
        history.ms = 0.
        reference_rollout(game, cfg, row, MeasuredPolicy(policy), cache, trace)
        row["timing"]["history_gru_ms"] = history.ms

    class MeasuredWorker(worker.Worker):
        def start(self):
            super().start()
            profile.meter.add(self.game.engine.proc.pid)

        def close(self):
            pid = None if self.game is None else self.game.engine.proc.pid
            try:
                super().close()
            finally:
                if pid is not None and pid in profile.meter.active:
                    profile.meter.retire(pid)

    class Fleet(reference_fleet):
        def run(self, *args):
            if not hasattr(self.local, "worker"):
                self.local.worker = MeasuredWorker(self.env, self.config, self.config["resident"])
                self.workers.append(self.local.worker)
            return self.local.worker.attempt(*args)

    if args.early_dispatch:
        # Replenish the same frozen policy batch before compressing and writing the finished root.
        source = getsource(reference_collect)
        source = profile_stock.replace(source, "            tick = perf_counter()",
                                       "            reserve()\n            tick = perf_counter()")
        source = profile_stock.replace(source, '            new_attempts += len(batch["rows"])\n            reserve()',
                                       '            new_attempts += len(batch["rows"])')
        namespace = scope.copy()
        exec(compile(source, reference_collect.__code__.co_filename, "exec"), namespace)
        reference_collect = namespace["collect"]

    def collect(fleet, store, stop, cfg, phase, stage, items, policy, model_hash, modes):
        profile.io.clear()
        tick = profile.meter.start_phase()
        result = reference_collect(fleet, store, stop, cfg, phase, stage, items, policy, model_hash, modes)
        resources = profile.meter.end_phase(tick)
        scan = perf_counter()
        batches = list(store.batches(phase, stage))
        roots = [b["timing"] for b in batches]
        rows = [r for b in batches for r in b["rows"]]
        clocks = [r["timing"] for r in rows if "timing" in r]
        root_fields = ("startup_ms", "handshake_ms", "initialize_ms", "snapshot_ms", "retirement_ms", "total_ms")
        turn_fields = ("features_ms", "forward_ms", "memory_choice_ms", "history_gru_ms", "rpc_ms",
                       "reset_ms", "close_ms", "engine_replay_ms", "engine_observe_ms", "engine_advance_ms")
        profile.record("collection", resources | result | dict(phase=phase, stage=stage, roots=len(roots),
                       write_breakdown_s=dict(profile.io),
                       root_phase_worker_ms={k: sum(r.get(k, 0.) for r in roots) for k in root_fields},
                       model_init_worker_ms=sum(r.get("build_phases", {}).get("model_init", 0.) for r in roots),
                       cold_roots=sum(not r["resident"] for r in roots),
                       cold_build_ms=quantiles([r["initialize_ms"] for r in roots if not r["resident"]]),
                       hot_build_ms=quantiles([r["initialize_ms"] for r in roots if r["resident"]]),
                       retirement=dict(Counter(r["retirement"] for r in roots)),
                       rollout_phase_worker_ms={k: sum(r.get(k, 0.) for r in clocks) for k in turn_fields},
                       statuses=dict(Counter(r["feedback"]["status"] for r in rows)),
                       attempted=len(rows), qualified=sum(r["feedback"]["eligible"] for r in rows),
                       transitions=sum(sum(s["advanced"] for s in r["transitions"]) for r in rows),
                       inference_ms=quantiles([x for r in rows for x in r["inference_ms"]]),
                       instrumentation_scan_s=perf_counter()-scan))
        return result

    def train(*pos):
        tick = profile.meter.start_phase()
        if args.threads != 1:
            torch.set_num_threads(args.threads)
        try:
            if args.mode == "stock":
                result = profile_stock.train(*pos)
            else:
                result = optimizer.train(*pos, mode=args.mode, microbatch=args.microbatch)
        finally:
            if args.threads != 1:
                torch.set_num_threads(1)
        profile.record("optimize", profile.meter.end_phase(tick) | result)
        return result

    def save(path, data, **kwargs):
        if path.parent.name != "audit-only":
            return save_json(path, data, **kwargs)
        tick = perf_counter()
        save_json(path, data, **kwargs)
        profile.io["audit_compress_write"] += perf_counter() - tick

    if args.early_dispatch:
        namespace["save_json"] = save

    class Journal(scope["Journal"]):
        def commit_root(self, *pos):
            tick = perf_counter()
            super().commit_root(*pos)
            profile.io["sqlite_compress_commit"] += perf_counter() - tick

        def save(self, step, *args):
            return profile.wrap("sqlite_checkpoint", super().save)(step, *args)

    def atomic_bytes(path, data):
        name = "checkpoint_export_file" if path.name == "checkpoint-latest.pt" else "review_file"
        return profile.wrap(name, scope["original_atomic_bytes"])(path, data)

    scope.update(Fleet=Fleet, collect=collect, train=train, Journal=Journal, save_json=save,
                 publish=profile.wrap("review_publish", scope["publish"]),
                 export_public=profile.wrap("final_export", scope["export_public"]),
                 tensor_bytes=profile.wrap("model_serialization", scope["tensor_bytes"]),
                 original_atomic_bytes=scope["atomic_bytes"], atomic_bytes=atomic_bytes)
    return rollout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=BASE / "formal.json")
    p.add_argument("--mode", choices=("stock", "micro", "features", "batched"), default="batched")
    p.add_argument("--workers", type=int)
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--microbatch", type=int, default=16)
    p.add_argument("--roots-per-update", type=int)
    p.add_argument("--through-update", type=int, default=3)
    p.add_argument("--early-dispatch", action="store_true")
    args = p.parse_args()
    cfg = protocol.read(args.config)
    for key, ceiling in (("workers", 16), ("roots_per_update", 1024)):
        if (value := getattr(args, key)) is not None:
            if not 1 <= value <= ceiling:
                p.error(f"{key} must be between 1 and {ceiling}")
            cfg[key] = value
    if not (0 <= args.through_update <= cfg["updates"]) or min(
            cfg["workers"], cfg["roots_per_update"], args.threads, args.microbatch) < 1:
        p.error("Invalid bounded run settings")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for directory in ("audit-only", "checkpoint-timings", "profiles"):
        (output / directory).mkdir(exist_ok=True)
    if not (protocol.ROOT / "logs/m1-nosl3c-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll").exists():
        runpy.run_path(str(BASE / "build.py"))["main"]()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    scope = runpy.run_path(str(BASE / "run.py"))["fit"].__globals__
    env = worker.Environment(output)
    identity = scope["run_identity"](cfg, env)
    identity["execution"] = dict(mode=args.mode, threads=args.threads, microbatch=args.microbatch,
                                 early_dispatch=args.early_dispatch)
    for name in ("runner", "resources", "optimizer", "features", "batched", "profile_stock"):
        identity["source"][f"ib/{name}"] = protocol.digest((HERE / f"{name}.py").read_text(encoding="utf-8"))
    path = output / "profiles" / f"invocation-{time_ns()}.json"
    stop = scope["Stop"](output, cfg["max_train_seconds"])
    signal.signal(signal.SIGINT, stop.signal)
    signal.signal(signal.SIGTERM, stop.signal)
    cache = FastCache if args.mode in ("features", "batched") else worker.DecisionCache
    with env.b1b.bank.writer(output), Meter() as meter:
        profile = Profile(path, meter)
        rollout = install(scope, profile, args)
        tick = meter.start_phase()
        try:
            with patch.object(worker, "rollout", rollout), patch.object(worker, "DecisionCache", cache):
                scope["fit"](output, env, cfg, identity, stop, args.through_update)
        except Exception as error:
            save_json(output / "audit-only" / f"fatal-{time_ns()}.json",
                      dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
            save_json(output / "run-status.json", dict(state="failed", type=type(error).__name__))
            raise
        finally:
            profile.record("fit", meter.end_phase(tick))
            profile.save()


if __name__ == "__main__":
    main()