"""Freeze disjoint roots and evaluate fixed direct public policies with a durable ledger."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
import gzip
import json
import os
from pathlib import Path
import sqlite3
import statistics
from threading import local
from time import perf_counter
from types import FunctionType, SimpleNamespace

import numpy as np
import torch

from sv_data import ROOT, PRE1, checksum, config, db_for, decoded, digest, encode, policy_key, write_json
from sv_model import VERSION
from sv_runtime import ValueActor
from evaluate import Actor, Decision, bind, teacher, verify_partition

SEEDS = dict(development=(71393013, 79193013), confirmation=(71393014, 79193014),
             experience=(71393015, 79193015))


def freeze(output, cfg):
    output.mkdir(parents=True, exist_ok=False)
    runtime, versions = bind(output, Path(cfg["host"]))
    with ExitStack() as stack:
        catalog = runtime["targets"].open_worker(output, stack, versions).request("synthetic_catalog")
    base = json.loads((PRE1 / "dev-roots.json").read_bytes())
    role, = [item for item in catalog["characters"] if item["name"] == "Ironclad"]
    allowed = ({card["id"] for card in role["cards"]} | set(base["generated_allow"])
               | {"FRANTIC_ESCAPE", "INFECTION", "TOXIC", "WITHER", "DISINTEGRATION", "MIND_ROT",
                  "SLOTH", "WASTE_AWAY", "AMNESIA"}) - set(base["exclude"])
    prior = json.loads(Path("logs/m1-pre1-dev-freeze/dev.json").read_bytes())
    families = {tuple(sorted(card["id"] for card in job[1]["deck"])) for job in prior["jobs"]}
    seeds = {job[1]["seed"] for job in prior["jobs"]}
    for phase, (root_seed, policy_seed) in SEEDS.items():
        rules = base | dict(version=f"ironclad.sv3a.{phase}.v1", seed=root_seed, policy_seed=policy_seed,
                            action_cap=256)
        count = cfg["eval_roots"] if phase != "experience" else 48
        jobs = []
        for i in range(count):
            spec, split, family, room = runtime["root"](catalog, rules, i)
            composition = tuple(sorted(card["id"] for card in spec["deck"]))
            if composition in families or spec["seed"] in seeds:
                raise ValueError("Frozen cohort overlaps another development cohort")
            seeds.add(spec["seed"])
            families.add(composition)
            jobs.append([i, spec, "train" if phase == "experience" else "evaluation", family, room])
        plan = dict(config=rules, purpose=phase, allowed=sorted(allowed), jobs=jobs,
                    versions=versions, catalog=digest(catalog))
        verify_partition(plan, [Path(path) for path in cfg["sources"].values()])
        write_json(output / f"{phase}.json", plan)
        print(phase, count, checksum(output / f"{phase}.json"), flush=True)


def arms(cfg):
    return ["a2", "joint", *(f"{method}-{seed}" for method in ("random", "pre1") for seed in cfg["seeds"]),
            f"pre1-{cfg['seeds'][0]}-prior"]


def metrics(rows):
    valid = [row for row in rows if row["complete"]]
    wins = [row for row in valid if row["status"] == "predicted_win"]
    losses = [row["root"]["hp"] - row["terminal"]["hp"] for row in valid]
    ratios = [row["terminal"]["hp"] / row["terminal"]["max_hp"] for row in valid]
    decisions = [row["length"] for row in rows]
    quantiles = lambda values: dict(zip(("p05", "p50", "p90", "p95", "p99"),
        np.quantile(values, [.05, .50, .90, .95, .99]).tolist())) if values else None
    mean = lambda values: statistics.mean(values) if values else None
    hp_wins = [row["terminal"]["hp"] for row in wins]
    tail = sorted(ratios)[:max(1, round(.1 * len(ratios)))]
    return dict(attempts=len(rows), status=dict(Counter(row["status"] for row in rows)), complete=len(valid),
        wins=len(wins), deaths=len(valid)-len(wins), win_rate=len(wins)/len(rows), death_rate=(len(valid)-len(wins))/len(rows),
        decisions=sum(decisions), decisions_mean=mean(decisions), decisions_quantiles=quantiles(decisions),
        net_loss_mean=mean(losses), net_loss_quantiles=quantiles(losses), final_hp_win=quantiles(hp_wins),
        final_fraction=quantiles(ratios), final_fraction_worst_decile=mean(tail),
        severe_net_loss=sum(loss >= .5 * row["root"]["hp"] for row, loss in zip(valid, losses, strict=True)),
        victory_hp_mean=mean(hp_wins))


def load_rows(output):
    with closing(db_for(output / "results.sqlite")) as db:
        return [decoded(expected, blob) for expected, blob in db.execute("SELECT sha,payload FROM rows ORDER BY ordinal")]


def write_results(output, wall):
    entries = load_rows(output)
    rows = [item["row"] for item in entries]
    score = metrics(rows)
    times = [t for item in entries for t in item["timings"]]
    scores = [d for item in entries for d in item["diagnostics"]]
    score.update(wall_s=wall, attempts_per_s=len(rows)/wall, complete_per_s=score["complete"]/wall,
                 feature_ms_p50_p95=np.quantile([t[0]*1000 for t in times], [.5,.95]).tolist() if times else None,
                 forward_ms_p50_p95=np.quantile([t[1]*1000 for t in times], [.5,.95]).tolist() if times else None)
    if scores:
        score["value_policy"] = {
            "decisions": len(scores), "outside_top_k": sum(d["greedy_outside_prior"] for d in scores),
            "rare_support_selected": sum(d["prior"] < .05 for d in scores),
            "chosen_prior_mean": statistics.mean(d["prior"] for d in scores),
            "chosen_death_mean": statistics.mean(d["death"] for d in scores),
            "q_advantage_over_prior_top_mean": statistics.mean(d["advantage"] for d in scores),
        }
    score["strata"] = {
        f"{field}={value}": metrics([row for row in rows if key(row) == value])
        for field,key in [("hp", lambda row: row["root"]["hp"]), ("room", lambda row: row["room"])]
        for value in sorted({key(row) for row in rows})
    }
    write_json(output / "summary.json", score)


def evaluate_arm(root, manifest_path, output, cfg, arm, workers, max_new=None):
    output.mkdir(parents=True, exist_ok=True)
    plan = json.loads(manifest_path.read_bytes())
    runtime, versions = bind(output, Path(cfg["host"]))
    if plan["versions"] != versions:
        raise ValueError("Evaluation host differs from frozen manifest")
    frozen_sha = checksum(manifest_path)
    collect = runtime["collect"]
    if arm == "a2":
        policy, identity = teacher(runtime, Path(cfg["teacher"]), 84)
        old_forward = policy.forward
        costs, diagnostics = local(), local()

        def forward(decision, history):
            tick = perf_counter()
            result = old_forward(decision, history)
            costs.measure.append((0., perf_counter() - tick))
            return result

        policy.forward = forward
    else:
        if arm == "joint":
            policy, identity = Actor(Path(cfg["pre1"])), checksum(Path(cfg["pre1"]))
            costs, diagnostics = policy.costs, local()
        else:
            checkpoint = root / arm.removesuffix("-prior") / "best.pt"
            stats = json.loads((checkpoint.parent / "summary.json").read_bytes())
            if stats["epochs"] != cfg["epochs"] and plan["purpose"] != "experience":
                raise ValueError("Formal battle evaluation requires the full training schedule")
            policy = ValueActor(checkpoint, Path(cfg["pre1"]), cfg["prior_top_k"], arm.endswith("-prior"))
            identity, costs, diagnostics = policy.identity, policy.costs, policy.costs
        old = collect.__wrapped__
        namespace = SimpleNamespace(base=SimpleNamespace(WIDTH=(3, 24)),
                                    project=runtime["targets"].project, Decision=Decision)
        collect = torch.inference_mode()(FunctionType(old.__code__, old.__globals__ | {"targets": namespace}))
    contract = dict(schema=VERSION, arm=arm, policy=identity, manifest=frozen_sha, workers=workers,
                    version=versions, implementation=checksum(Path(__file__)), purpose=plan["purpose"])
    lanes, thread = [], local()
    read = lambda ordinal: int(ordinal)
    log = output / "results.sqlite"
    wall = 0.
    with closing(sqlite3.connect(output / "writer.sqlite", timeout=0)) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        with closing(sqlite3.connect(log, timeout=30)) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS contract(sha TEXT PRIMARY KEY,json BLOB);
                CREATE TABLE IF NOT EXISTS rows(ordinal INTEGER PRIMARY KEY,sha TEXT,payload BLOB);
                CREATE TABLE IF NOT EXISTS sessions(seconds REAL);
            """)
            old = db.execute("SELECT sha FROM contract").fetchone()
            signature = digest(contract)
            if old and old[0] != signature:
                raise ValueError("Battle evaluation resume contract changed")
            with db:
                db.execute("INSERT OR IGNORE INTO contract VALUES (?,?)", (signature, encode(contract)))
            finished = {read(row[0]) for row in db.execute("SELECT ordinal FROM rows")}
            remaining = [job for job in plan["jobs"] if job[0] not in finished][:max_new]
            if remaining:
                start = perf_counter()
                with runtime["p0"]["Meter"]() as meter:
                    def one(job):
                        if not hasattr(thread, "lane"):
                            lane = thread.lane = runtime["Lane"](output, versions, meter, 96, 512 * 2**20)
                            lanes.append(lane)
                        costs.measure = []
                        diagnostics.diagnostics = []
                        ordinal, spec, split, family, room = job
                        task = digest([frozen_sha, identity, ordinal])
                        row, cost = collect(versions, policy, policy, identity, plan["config"], set(plan["allowed"]),
                                            (task, ordinal, spec, split, family, room), thread.lane, True)
                        if arm != "a2":
                            row["behavior"]["model"] = (VERSION if isinstance(policy, ValueActor)
                                                        else "sts2.pre1.ironclad.public.v1")
                            row["behavior"]["mode"] = "greedy_topk" if arm.endswith("-prior") else (
                                "greedy" if isinstance(policy, ValueActor) else "sample")
                        row["purpose"] = plan["purpose"]
                        return ordinal, dict(row=row, cost=cost, timings=costs.measure,
                                              diagnostics=diagnostics.diagnostics)

                    try:
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            for offset in range(0, len(remaining), workers * 4):
                                for ordinal, result in pool.map(one, remaining[offset:offset + workers * 4]):
                                    raw = encode(result)
                                    from hashlib import sha256
                                    with db:
                                        db.execute("INSERT INTO rows VALUES (?,?,?)",
                                            (ordinal, sha256(raw).hexdigest(), gzip.compress(raw, compresslevel=3, mtime=0)))
                                if (offset // (workers * 4)) % 4 == 0:
                                    print(plan["purpose"], arm, len(finished) + min(offset + workers*4, len(remaining)),
                                          "/", len(plan["jobs"]), flush=True)
                    finally:
                        for lane in lanes:
                            lane.close("sv3a_evaluation")
                        with db:
                            db.execute("INSERT INTO sessions VALUES (?)", (perf_counter() - start,))
            wall = db.execute("SELECT sum(seconds) FROM sessions").fetchone()[0]
    if wall:
        write_results(output, wall)


if __name__ == "__main__":
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", type=Path)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--phase", choices=("development", "confirmation", "experience", "both"), default="both")
    parser.add_argument("--arms", nargs="+")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--max-new", type=int)
    args = parser.parse_args()
    cfg = config()
    if args.freeze:
        freeze(args.manifests.resolve(), cfg)
    else:
        phases = ("development", "confirmation") if args.phase == "both" else [args.phase]
        for phase in phases:
            for arm in args.arms or arms(cfg):
                evaluate_arm(args.models, args.manifests / f"{phase}.json", args.output / phase / arm,
                             cfg, arm, args.workers or cfg["eval_workers"], args.max_new)
