"""Run bounded, serial A/B benchmarks and summarize durable public evidence."""
import argparse
import gzip
from collections import Counter
from pathlib import Path
import json
import platform
import subprocess
import sys
from time import perf_counter

import torch

from features import BASE, HERE, protocol
from verify import LIMITS, database, rows_at, snapshot
from nosl_experience import save_json
from nosl_run import quantiles

TRAIN = "train"


def run(root, name, mode, workers, updates, roots, early=False, *, threads=1, microbatch=16):
    output = root / name
    if output.exists():
        raise FileExistsError(output)
    cmd = [sys.executable, str(HERE / "runner.py"), str(output), "--mode", mode,
           "--workers", str(workers), "--through-update", str(updates), "--roots-per-update", str(roots),
           "--threads", str(threads), "--microbatch", str(microbatch)]
    if early:
        cmd.append("--early-dispatch")
    tick = perf_counter()
    with (root / f"{name}.log").open("wb") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=protocol.ROOT)
    process_wall = perf_counter() - tick
    save_json(output / "driver.json", dict(process_wall_s=process_wall, mode=mode, workers=workers,
                                          updates=updates, roots_per_update=roots, early=early,
                                          threads=threads, microbatch=microbatch))
    print(f"{name} finished in {process_wall:.2f}s", flush=True)


def sum_fields(events, field):
    result = Counter()
    for row in events:
        result.update(row[field])
    return dict(result)


def summary(path):
    profiles = sorted((path / "profiles").glob("invocation-*.json"))
    if len(profiles) != 1:
        raise ValueError(f"Expected exactly one uninterrupted process profile for {path.name}")
    payload = json.loads(profiles[0].read_bytes())
    events = payload["events"]
    training = [e for e in events if e["event"] == "collection" and e["phase"] == TRAIN]
    opt = [e for e in events if e["event"] == "optimize"]
    assert len(training) == len(opt)
    with database(path / "training.sqlite") as db:
        rows = [r for stage in range(len(training)) for r in rows_at(db, stage)]
        identity = json.loads(db.execute("SELECT value FROM identity").fetchone()[0])
        models = [snapshot(db, step)["model_sha256"] for step in range(len(training) + 1)]
    driver = path / "driver.json"
    fit = next(e for e in events if e["event"] == "fit")
    phases = [e for e in events if e["event"] != "fit"]
    wall = sum(e["collect_s"] for e in training) + sum(e["wall_s"] for e in opt) + sum(
        e["wall_s"] for e in phases if e["event"] == "sqlite_checkpoint") - next(
        e["wall_s"] for e in events if e["event"] == "sqlite_checkpoint")
    eligible = sum(r["feedback"]["eligible"] for r in rows)
    attempted = len(rows)
    moves = sum(t["transitions"] for t in training)
    inference = quantiles([x for r in rows for x in r["inference_ms"]])
    performance = dict(qualified=eligible, attempts=attempted, moves=moves, updates=len(training),
                       qualified_per_s=eligible/wall, attempted_per_s=attempted/wall,
                       transitions_per_s=moves/wall, training_wall_s=wall, fit_wall_s=fit["wall_s"],
                       fit_qualified_per_s=eligible/fit["wall_s"],
                       training_collection_s=sum(e["collect_s"] for e in training),
                       fit_cpu_cores=fit["occupied_cores"], fit_cpu_pct=fit["total_cpu_pct"],
                       peak_rss_mb=payload["peak_rss_mb"], inference_ms=inference,
                       optimizer_wall_per_update=[e["wall_s"] for e in opt],
                       statuses=sum_fields(training, "statuses"),
                       retirement=sum_fields(training, "retirement"))
    return dict(**performance, identity=identity, models=models, logical_cpus=payload["logical_cpus"],
                driver=json.loads(driver.read_bytes()) if driver.exists() else None, phases=phases)


def audit_signatures(root, stage):
    for path in (root / "audit-only").glob(f"train-{stage}-*.json.gz"):
        row = json.loads(gzip.decompress(path.read_bytes()))
        yield path.name, (row.get("exact_root_sha256"), protocol.digest(row["traces"]))


def paired(left, right, n):
    def data(db, stage):
        return {(r["root"], r["replicate"]): r for r in rows_at(db, stage)}

    stages = []
    with database(left / "training.sqlite") as a, database(right / "training.sqlite") as b:
        for stage in range(n):
            p, q = data(a, stage), data(b, stage)
            assert p.keys() == q.keys()
            left_audit, right_audit = dict(audit_signatures(left, stage)), dict(audit_signatures(right, stage))
            assert left_audit.keys() == right_audit.keys()
            counts = Counter(episodes=len(p), native_roots=len(left_audit))
            for key, (exact, trace) in left_audit.items():
                counts["same_native_root"] += exact is not None and exact == right_audit[key][0]
                counts["same_native_action_stamps"] += trace == right_audit[key][1]
            for key, x in p.items():
                y = q[key]
                assert x["behavior"]["seed"] == y["behavior"]["seed"]
                x_steps, y_steps = x["transitions"], y["transitions"]
                counts["same_termination"] += x["feedback"] == y["feedback"]
                fields = ("observation", "action", "next_observation", "advanced")
                same = len(x_steps) == len(y_steps) and all(
                    all(k[v] == l[v] for v in fields) for k, l in zip(x_steps, y_steps))
                counts["same_full_trajectory"] += same
                for k, l in zip(x_steps, y_steps):
                    if k["observation"] != l["observation"]:
                        break
                    for field in ("policy_logp", "value"):
                        kf, lf = k[field], l[field]
                        delta = max(abs(i - j) for i, j in zip(kf, lf, strict=True))
                        counts[f"max_abs_{field}"] = max(counts[f"max_abs_{field}"], delta)
                    if k["action"] != l["action"]:
                        counts["different_action_at_same_public_prefix"] += 1
                        break
            al, bl = snapshot(a, stage + 1), snapshot(b, stage + 1)
            weights_a = al["weights"]["mechanism"]["weights"]
            weights_b = bl["weights"]["mechanism"]["weights"]
            counts["max_abs_parameter"] = max((v - weights_b[k]).abs().max().item() for k, v in weights_a.items())
            counts["exact_model_hash"] = al["model_sha256"] == bl["model_sha256"]
            stages.append(dict(stage=stage, **counts))
    return stages


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--suite", choices=("matrix", "workers", "large", "tune", "summarize"), default="matrix")
    p.add_argument("--winner", type=int, default=6)
    p.add_argument("--early", action="store_true", help="Use the measured early-dispatch variant in the large run")
    p.add_argument("--names", nargs="+")
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    roots = protocol.read(BASE / "formal.json")["roots_per_update"]
    repeats = LIMITS["short_updates"]
    if args.suite == "matrix":
        cases = [(m, m, 4, repeats, roots, False) for m in ("stock", "micro", "features", "batched")]
    elif args.suite == "workers":
        cases = [(f"w{w}", "batched", w, repeats, roots, False) for w in LIMITS["worker_sweep"]]
        cases.append((f"w{args.winner}-early", "batched", args.winner, repeats, roots, True))
    elif args.suite == "large":
        cases = [("large-stock", "stock", 4, repeats, LIMITS["large_roots"], False),
                 ("large-batched", "batched", args.winner, repeats, LIMITS["large_roots"], args.early)]
    else:
        cases = []
    if args.suite == "tune":
        reference = args.output / "large-batched"
        if not (reference / "driver.json").is_file():
            p.error("Run the large suite in this output directory before tuning")
        driver = json.loads((reference / "driver.json").read_bytes())
        run(args.output, "large-tuned", "batched", driver["workers"], repeats, LIMITS["large_roots"],
            driver["early"], threads=4, microbatch=32)
        args.names = ["large-batched", "large-tuned"]
    for name, m, w, u, r, early in cases:
        run(args.output, name, m, w, u, r, early=early)
    names = args.names or [case[0] for case in cases]
    if not names:
        p.error("--names required to summarize existing sibling runs")
    profiles = {n: summary(args.output / n) for n in names}
    comparisons = {n: paired(args.output / names[0], args.output / n, min(profiles[names[0]]["updates"],
                                                                         profiles[n]["updates"]))
                   for n in names[1:]}
    if args.suite == "workers":
        for stages in comparisons.values():
            for stage in stages:
                assert stage["exact_model_hash"]
                assert stage["episodes"] == stage["same_full_trajectory"] == stage["same_termination"]
                assert stage["native_roots"] == stage["same_native_root"] == stage["same_native_action_stamps"]
    save_json(args.output / f"{args.suite}-summary.json",
              dict(platform=platform.platform(), cpu=platform.processor(), torch=str(torch.__version__),
                   cuda=torch.cuda.is_available(), profiles=profiles, paired=comparisons))


if __name__ == "__main__":
    main()
