"""Run or resume NOSL3C from a fixed, resource-free protocol."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
import json
from pathlib import Path
import runpy
import signal
from threading import Event, local
from time import perf_counter, time_ns
import traceback

import torch

from journal import Journal, atomic_bytes, fresh, load, state
from learning import train
from protocol import HERE, ROOT, digest, read, root
from review import export_public, metric, publish, training_summary
from worker import Environment, Worker
from nosl3b_store import tensor_bytes
from nosl_experience import save_json


class Stop:
    def __init__(self, output, seconds):
        self.flag = Event()
        self.deadline = perf_counter() + seconds if seconds else None
        self.file = output / "STOP"

    def signal(self, *_):
        self.flag.set()

    def requested(self):
        return (self.flag.is_set() or self.file.exists() or
                (self.deadline is not None and perf_counter() >= self.deadline))


class Fleet:
    def __init__(self, env, config):
        self.config, self.env = config, env
        self.local = local()
        self.workers = []
        self.pool = ThreadPoolExecutor(max_workers=config["workers"])

    def run(self, *args):
        if not hasattr(self.local, "worker"):
            self.local.worker = Worker(self.env, self.config, self.config["resident"])
            self.workers.append(self.local.worker)
        return self.local.worker.attempt(*args)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        for worker in self.workers:
            worker.close()


def collect(fleet, store, stop, config, phase, stage, items, policy, model_hash, modes):
    started = perf_counter()
    root_ids = {r["id"] for r in items}
    existing = store.done(phase, stage)
    if len(root_ids) != len(items) or not existing <= root_ids:
        raise ValueError("Persisted root enumeration conflicts with protocol")
    prior_spans = {}
    if existing:
        for previous in store.batches(phase, stage):
            if clock := previous.get("scheduler_clock"):
                span = prior_spans.setdefault(clock["id"], [0., 0.])
                span[0] = max(span[0], clock["seconds"])
                span[1] = max(span[1], clock["writes_seconds"])
    span_id = str(time_ns())
    pending = iter(r for r in items if r["id"] not in existing)
    futures = {}
    writes, new_attempts = 0., 0

    def reserve():
        if not stop.requested() and (item := next(pending, None)) is not None:
            future = fleet.pool.submit(fleet.run, item, stage, model_hash, policy, modes)
            futures[future] = item

    for _ in range(config["workers"]):
        reserve()
    while futures:
        finished, _ = wait(futures, return_when=FIRST_COMPLETED)
        for future in finished:
            item = futures.pop(future)
            batch, audit = future.result()
            if (batch["root"] != item["id"] or
                [(r["mode"], r["replicate"]) for r in batch["rows"]] != modes):
                raise ValueError("Worker did not return the reserved attempts")
            tick = perf_counter()
            private = fleet.env.output / "audit-only" / f"{phase}-{stage}-{item['id']}.json.gz"
            if private.exists():
                private = private.with_name(f"{private.stem}-{time_ns()}.json.gz")
            save_json(private, audit, compress=True)
            batch["scheduler_clock"] = dict(id=span_id, seconds=perf_counter()-started,
                                            writes_seconds=writes+perf_counter()-tick)
            store.commit_root(phase, stage, batch)
            writes += perf_counter() - tick
            new_attempts += len(batch["rows"])
            reserve()
    return dict(complete=store.done(phase, stage) == root_ids,
                collect_s=perf_counter()-started+sum(x[0] for x in prior_spans.values()),
                writes_s=writes+sum(x[1] for x in prior_spans.values()), new_attempts=new_attempts)


def qualify(rows, config, phase):
    n = len(rows)
    valid = sum(row["feedback"]["eligible"] for row in rows)
    faults = sum(row["feedback"]["status"] in ("error", "timeout") for row in rows)
    if valid / n < config["min_qualified"] or faults / n > config["max_fault_fraction"]:
        raise RuntimeError(f"{phase} qualification gate: {valid}/{n} qualified, {faults}/{n} faults")


def evaluate(fleet, store, stop, config, phase, step, policy, model_hash):
    items = [root(config, phase, i) for i in range(len(config[phase]) * config["evaluation_reps"])]
    modes = [("sample", 0), ("greedy", 0)]
    timing = collect(fleet, store, stop, config, phase, step, items, policy, model_hash, modes)
    if not timing["complete"]:
        return None
    rows = list(store.rows(phase, step))
    qualify(rows, config, phase)
    result = {mode: metric([r for r in rows if r["mode"] == mode]) for mode, _ in modes}
    for m in result.values():
        m["phase_collect_seconds"] = timing["collect_s"]
    return result


def fit(output, env, cfg, identity, stop, through):
    with closing(Journal(output / "training.sqlite", identity)) as store:
        latest = store.latest()
        if latest is None:
            policy, optimizer = fresh(cfg)
            store.save(0, state(policy, optimizer, cfg, 0), {})
            latest = 0
        snapshot, _ = store.load(latest)
        policy, optimizer = load(snapshot, cfg, latest)
        mode = [("sample", i) for i in range(cfg["traces_per_root"])]
        with closing(Fleet(env, cfg)) as fleet:
            while True:
                checkpoint = output / "checkpoint-latest.pt"
                tick = perf_counter()
                atomic_bytes(checkpoint, tensor_bytes(snapshot))
                export_s = perf_counter() - tick
                model_hash = snapshot["model_sha256"]
                save_json(output / "run-status.json", dict(state="running", update=latest, model_sha256=model_hash,
                                                           checkpoint_export_s=export_s))
                if stop.requested():
                    break
                if latest % cfg["review_interval"] == 0 or latest == cfg["updates"]:
                    summary_path = output / "reviews" / f"u{latest:06d}" / "review-summary.json"
                    if not summary_path.is_file():
                        # Review workers are scoped to this review, not kept idle through training.
                        with closing(Fleet(env, cfg)) as evaluator:
                            selection = evaluate(evaluator, store, stop, cfg, "selection", latest, policy, model_hash)
                            if selection is None or stop.requested():
                                break
                            final = None
                            if latest == cfg["updates"]:
                                final = evaluate(evaluator, store, stop, cfg, "report", latest, policy, model_hash)
                                if final is None:
                                    break
                        review = publish(output, store, cfg, latest, model_hash, selection, final)
                    else:
                        review = json.loads(summary_path.read_bytes())
                        if review["model_sha256"] != model_hash:
                            raise ValueError("Stored review refers to a different model")
                        save_json(output / "review-summary.json", review)
                        atomic_bytes(output / "review-summary.md", summary_path.with_suffix(".md").read_bytes())
                    print(f"review {latest}: {review['cumulative']['qualified']} qualified", flush=True)
                if latest >= through:
                    break
                items = [root(cfg, "train", i) for i in range(snapshot["next_root"],
                         snapshot["next_root"] + cfg["roots_per_update"])]
                clock = collect(fleet, store, stop, cfg, "train", latest, items, policy, model_hash, mode)
                if not clock["complete"] or stop.requested():
                    break
                batches = list(store.batches("train", latest))
                rows = [r for b in batches for r in b["rows"]]
                qualify(rows, cfg, "training")
                optimize = train(policy, optimizer, rows, cfg, model_hash)
                optimize["new_attempts_this_invocation"] = clock["new_attempts"]
                stats = training_summary(batches, clock["collect_s"], optimize, clock["writes_s"])
                latest += 1
                snapshot = state(policy, optimizer, cfg, latest)
                tick = perf_counter()
                store.save(latest, snapshot, stats)
                checkpoint_s = perf_counter() - tick
                save_json(output / "checkpoint-timings" / f"u{latest:06d}.json",
                          dict(seconds=checkpoint_s, model_sha256=snapshot["model_sha256"]))
                print(f"update {latest}: {optimize['qualified']}/{len(rows)} qualified;"
                      f" collection {clock['collect_s']:.2f}s; optimizer {optimize['seconds']:.2f}s;"
                      f" checkpoint {checkpoint_s:.3f}s", flush=True)
        export_public(output, store)
        is_final = latest == cfg["updates"] and len(store.done("report", latest)) == len(cfg["report"]) * cfg["evaluation_reps"]
        save_json(output / "run-status.json", dict(state="complete" if is_final else "stopped",
                  update=latest, stop_requested=stop.requested(), model_sha256=snapshot["model_sha256"],
                  pending_training_roots=len(store.done("train", latest))))


def run_identity(cfg, env):
    names = ("run", "worker", "learning", "journal", "protocol", "review", "build", "audit_value")
    source = {n: digest((HERE / f"{n}.py").read_text(encoding="utf-8")) for n in names}
    deps = ("m1-nosl3a/nosl_model.py", "m1-nosl3a/nosl_experience.py", "m1-nosl3b/nosl3b_store.py",
            "m1-nosl3b/nosl3b_episode.py", "m1-nosl3b/analyze.py")
    source.update({n: digest((HERE.parent / n).read_text(encoding="utf-8")) for n in deps})
    return dict(config_sha256=digest(cfg), engine=env.versions, source=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE / "formal.json")
    parser.add_argument("--through-update", type=int, help="Pause at this durable update, preserving the frozen final budget")
    args = parser.parse_args()
    cfg = read(args.config)
    through = cfg["updates"] if args.through_update is None else args.through_update
    if not 0 <= through <= cfg["updates"]:
        parser.error("Pause budget is outside the frozen protocol")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for directory in ("audit-only", "checkpoint-timings"):
        (output / directory).mkdir(exist_ok=True)
    if not (ROOT / "logs/m1-nosl3c-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll").exists():
        runpy.run_path(str(HERE / "build.py"))["main"]()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    env = Environment(output)
    identity = run_identity(cfg, env)
    stop = Stop(output, cfg["max_train_seconds"])
    signal.signal(signal.SIGINT, stop.signal)
    signal.signal(signal.SIGTERM, stop.signal)
    with env.b1b.bank.writer(output):
        try:
            fit(output, env, cfg, identity, stop, through)
        except Exception as error:
            detail = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
            save_json(output / "audit-only" / f"fatal-{time_ns()}.json", detail)
            save_json(output / "run-status.json", dict(state="failed", type=type(error).__name__))
            raise


if __name__ == "__main__":
    main()