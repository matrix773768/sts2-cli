"""Cooperative adapters around the existing DC1, SV3A and SV4A routines."""

import argparse
from collections import Counter
from contextlib import closing
from itertools import islice
import json
from pathlib import Path
import sqlite3
import sys

# Run as an explicit script with either the base interpreter or the CUDA venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.training_manager.common import ROOT, checksum, read, write
from tools.training_manager.worker import PAUSED, progress, stop_requested


def load_research():
    sys.path.insert(0, str(ROOT / "experiments/m1-dc1"))
    import dc_common
    import torch
    return dc_common, torch


def committed(db):
    if not db.exists():
        return 0
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as session:
        return session.execute("SELECT count(*) FROM results").fetchone()[0]


def battle(args):
    dc, _ = load_research()
    from dc_produce import get_jobs
    from loop_battle import Host, run, summary
    from sv_model import load

    cfg = dc.config() | {"direct_stop_margin": 0.0}
    dest = args.work / "battle"
    roots = args.work / "roots.json"
    if args.operation == "dc1":
        cohort = get_jobs(args.reference, cfg, args.round, args.count)
        weights, condition, budget = dc.arms()[args.arm]
        epsilon = .05
    else:
        source = read(args.reference)
        if source["purpose"] not in ("development", "development-controls"):
            raise ValueError("Only development manifests are eligible for this evaluation")
        cohort = source | {"jobs": source["jobs"][:args.count]}
        if args.experience:
            training = read(args.experience)
            families = {job[3] for job in training["jobs"]}
            seeds = {job[1]["seed"] for job in training["jobs"]}
            if any(job[3] in families or job[1]["seed"] in seeds for job in cohort["jobs"]):
                raise ValueError("Development roots overlap experience roots")
        weights = args.weights
        _, snapshot = load(weights)
        condition, budget, epsilon = snapshot["policies"][-1], 0, 0.
    if len(cohort["jobs"]) != args.count:
        raise ValueError("The requested root budget exceeds the approved cohort")
    dc.frozen(roots, cohort)
    ledger = dest / "results.sqlite"
    done = committed(ledger)
    host = None
    while True:
        if done == args.count or stop_requested():
            report = read(dest / "summary.json", {})
            if done == args.count and report.get("attempts") != done:
                # The final row may have committed immediately before a crash.
                with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                    wall = db.execute("SELECT sum(seconds) FROM sessions").fetchone()[0]
                report = summary(dest, wall or 1e-9)
            if report.get("status", {}).get("error") or report.get("counts", {}).get("terminal_mismatch"):
                raise ValueError("Battle execution or terminal verification errors")
            progress(done, args.count, ledger if done else None, throughput=report.get("complete_per_s"),
                     complete=report.get("complete"), terminals=report.get("status"), manifest=str(roots))
            return 0 if done == args.count else PAUSED
        if host is None:
            host = Host(args.work, args.host, cfg)
        report = run(host, roots, dest, cfg, weights, condition, budget, epsilon=epsilon,
                     attempts=args.count, max_new=args.chunk)
        done = committed(ledger)
        progress(done, args.count, ledger, throughput=report["complete_per_s"],
                 complete=report["complete"], terminals=report["status"], manifest=str(roots))
        if report["status"].get("error") or report["counts"].get("terminal_mismatch"):
            raise ValueError("Battle execution or terminal verification errors")


def features(args):
    dc, _ = load_research()
    from loop_battle import read_ledger
    from sv_data import Encoder, Shards, examples, policy_key
    from sv_model import load

    _, parent = load(args.parent)
    encoder = Encoder(parent["vocabulary"])
    root_path = args.experience / "roots.json"
    ledger = args.experience / "battle"
    database = ledger / "results.sqlite"
    roots = read(root_path)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        production = json.loads(db.execute("SELECT json FROM contract").fetchone()[0])
    definition = production["definition"]
    key = f"sts2.sv4a.prediction_only.v1|{dc.digest(definition)}|conditional"
    slot = len(parent["policies"])
    target = len(roots["jobs"])
    if (not production["purpose"].startswith("experience_") or production["purpose"] != roots["purpose"]
            or production["manifest"] != checksum(root_path) or definition["model"] != checksum(args.parent)
            or definition["continuation"] not in parent["policies"] or key in parent["policies"]
            or slot >= parent["spec"]["policy_slots"] or committed(database) != target
            or len({job[3] for job in roots["jobs"]}) != target):
        raise ValueError("Replay inputs fail the experience or parent identity contract")
    identity = dict(ledger=checksum(database), roots=checksum(root_path), parent=checksum(args.parent),
                    examples=12, chunk=args.chunk)
    state_path = args.work / "feature-state.json"
    state = read(state_path, dict(identity=identity, done=0, shards={"train": [], "validation": []}, sizes={}))
    if state["identity"] != identity:
        raise ValueError("Feature checkpoint identity changed")
    for group in state["shards"].values():
        for item in group:
            if checksum(args.work / item["name"]) != item["sha256"]:
                raise ValueError("Committed feature shard changed")
    sizes = Counter(state["sizes"])
    rows = islice(read_ledger(ledger), state["done"], None)
    while state["done"] < target:
        start = state["done"]
        if stop_requested():
            progress(start, target, state_path if start else None)
            return PAUSED
        batch = list(islice(rows, args.chunk))
        if not batch:
            raise ValueError("Experience ended before the frozen target")
        block = args.work / f"shard-{start:06}"
        block.mkdir(exist_ok=True)
        writer = Shards(block)
        for ordinal, item in enumerate(batch, start):
            row = item["row"]
            idx, private, split, family, room = roots["jobs"][ordinal]
            if (item["ordinal"] != idx or policy_key(row["behavior"]) != key or row["family"] != family
                    or row["split"] != split or row["room"] != room
                    or row["root"] != {k: v for k, v in private.items() if k != "seed"}):
                raise ValueError("Experience row does not match the frozen root")
            if row["complete"]:
                encoded = list(examples(row, encoder, dict(hp_bins=parent["spec"]["bins"]), slot, ordinal, 12))
                writer.add(split, encoded)
                sizes[split] += 1
                sizes[split + "_rows"] += len(encoded)
        for split in writer.paths:
            writer.flush(split)
            state["shards"][split].extend(item | {"name": f"{block.name}/{item['name']}"}
                                          for item in writer.paths[split])
        state.update(done=start + len(batch), sizes=dict(sizes))
        write(state_path, state)
        progress(state["done"], target, state_path, sizes=dict(sizes))
    if not all(state["shards"].values()):
        raise ValueError("Training and validation must both contain complete trajectories")
    manifest = args.work / "manifest.json"
    write(manifest, dict(identity=identity, policy=key, definition=definition, slot=slot, sizes=sizes,
                         shards=state["shards"], vocabulary=parent["vocabulary"], spec=parent["spec"]))
    progress(target, target, manifest, sizes=dict(sizes))
    return 0


def learn(args):
    _, torch = load_research()
    from loop_common import config
    from loop_learn import fit
    from sv_model import load
    from sv_train import load_data, train_arm

    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("high")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA is unavailable in the approved Python environment")
    path = args.work / "resume.pt"
    if args.operation == "sv4-train":
        cfg = config() | {"epochs": args.epochs, "updates_per_epoch": args.updates}
        history = args.history
        if args.history_shards:
            # A smoke run reads a frozen subset of the existing historical replay.
            history = args.work / "history"
            history.mkdir(exist_ok=True)
            source = read(args.history / "manifest.json")
            groups = {split: [item | {"name": str(args.history / item["name"])}
                              for item in items[:args.history_shards]] for split, items in source["shards"].items()}
            manifest = history / "manifest.json"
            from dc_common import frozen
            frozen(manifest, source | {"shards": groups})
    else:
        from sv_data import config as sv3_config
        cfg = sv3_config() | {"epochs": args.epochs}
        dataset, shards = load_data(args.current, args.history_shards)
    saved = torch.load(path, map_location="cpu", weights_only=True) if path.exists() else None
    epoch = saved["epoch"] if saved else 0
    while epoch < args.epochs:
        if stop_requested():
            progress(epoch, args.epochs, path if epoch else None, updates=saved["updates"] if saved else 0)
            return PAUSED
        if args.operation == "sv4-train":
            fit(history, args.current, None, args.parent, args.optimizer, args.work, cfg, args.device, epoch + 1)
        else:
            train_arm(args.current, dataset, shards, args.work, cfg, args.arm, cfg["seeds"][0],
                      args.device, epoch + 1, warm=args.optimizer)
        saved = torch.load(path, map_location="cpu", weights_only=True)
        if saved["epoch"] != epoch + 1:
            raise ValueError("Trainer did not commit the requested epoch")
        epoch = saved["epoch"]
        progress(epoch, args.epochs, path, updates=saved["updates"], device=args.device,
                 throughput=saved["updates"] / max(.001, saved.get("seconds", saved.get("elapsed", 0.))))
    if args.operation == "sv4-train":
        train_state = torch.load(args.work / "best-train.pt", map_location="cpu", weights_only=True)
        _, best = load(args.work / "best.pt")
        if (saved["updates"] != args.epochs * args.updates or best["epoch"] != train_state["epoch"]
                or best["epoch"] > epoch or best["identity"] != train_state["identity"]
                or not all(torch.equal(tensor, train_state["model"][k]) for k, tensor in best["model"].items())):
            raise ValueError("Committed updates or deployment model/optimizer pair do not match")
    progress(epoch, args.epochs, path, updates=saved["updates"], device=args.device,
             throughput=saved["updates"] / max(.001, saved.get("seconds", saved.get("elapsed", 0.))),
             best_sha256=checksum(args.work / "best.pt"), checkpoint_sha256=checksum(path))
    return 0


def positive(value):
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("dc1", "development"):
        sub = commands.add_parser(name)
        sub.add_argument("work", type=Path)
        sub.add_argument("reference", type=Path)
        sub.add_argument("--host", type=Path, default=ROOT / "logs/m1-sv4a-host")
        sub.add_argument("--count", type=positive, required=True)
        sub.add_argument("--chunk", type=positive, required=True)
        if name == "dc1":
            sub.add_argument("--round", type=int, required=True)
            sub.add_argument("--arm", choices=("D2", "D2-search"), default="D2")
        else:
            sub.add_argument("--weights", type=Path, required=True)
            sub.add_argument("--experience", type=Path)
    sub = commands.add_parser("features")
    for key in ("work", "experience", "parent"):
        sub.add_argument(key, type=Path)
    sub.add_argument("--chunk", type=positive, required=True)
    for name in ("sv4-train", "sv3-train"):
        sub = commands.add_parser(name)
        sub.add_argument("work", type=Path)
        sub.add_argument("current", type=Path)
        sub.add_argument("--history-shards", type=positive)
        sub.add_argument("--epochs", type=positive, required=True)
        sub.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
        if name == "sv4-train":
            for key in ("history", "parent", "optimizer"):
                sub.add_argument(f"--{key}", type=Path, required=True)
            sub.add_argument("--updates", type=positive, required=True)
        else:
            sub.add_argument("--optimizer", type=Path)
            sub.add_argument("--arm", choices=("random", "pre1"), default="pre1")
    args = parser.parse_args()
    if args.operation in ("dc1", "development"):
        return battle(args)
    if args.operation == "features":
        return features(args)
    return learn(args)


if __name__ == "__main__":
    raise SystemExit(main())
