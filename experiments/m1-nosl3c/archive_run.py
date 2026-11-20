"""Verify and export a completed run's public evidence and execution costs."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3

from audit_value import main as audit_hp
from journal import load
from protocol import HERE, digest, read
from review import performance
from nosl3b_store import tensors, unpack
from nosl_experience import save_json
from nosl_run import quantiles


def build(run, output, config):
    status = json.loads((run / "run-status.json").read_bytes())
    if status["state"] != "complete" or status["update"] != config["updates"]:
        raise ValueError("The formal run must complete before publication")
    uri = (run / "training.sqlite").resolve().as_uri() + "?mode=ro"
    output.mkdir(parents=True, exist_ok=False)
    with closing(sqlite3.connect(uri, uri=True)) as db:
        identity = json.loads(db.execute("SELECT value FROM identity WHERE id=1").fetchone()[0])
        if identity["config_sha256"] != digest(config):
            raise ValueError("Publication configuration differs from ledger contract")
        by_step = {}
        train_hashes = {}
        root_timings, rows_expected, transitions = [], {}, 0
        statuses = {}
        envelope_keys = set()
        checkpoints = [*range(0, config["updates"], config["review_interval"]), config["updates"]]
        seals = {}
        for step, payload, sha, stats in db.execute("SELECT step,payload,sha,stats FROM snapshots ORDER BY step"):
            if sha256(payload).hexdigest() != sha:
                raise ValueError(f"Invalid checkpoint seal at {step}")
            saved = tensors(payload)
            train_hashes[step] = saved["model_sha256"]
            if step:
                by_step[step] = unpack(stats)
            if step in checkpoints:
                load(saved, config, step)
                path = output / f"checkpoint-u{step:06d}.pt"
                path.write_bytes(payload)
                seals[step] = dict(file=path.name, file_sha256=sha, model_sha256=saved["model_sha256"])
        for phase, step, root, raw, sha in db.execute(
                "SELECT phase,step,root,rows,sha FROM roots JOIN root_hashes USING (phase,step,root)"):
            if sha256(raw).hexdigest() != sha:
                raise ValueError(f"Damaged ledger row in {phase}/{step}")
            batch = unpack(raw)
            statuses.setdefault(phase, Counter()).update(r["feedback"]["status"] for r in batch["rows"])
            if phase not in ("train", "selection", "report"):
                continue
            if phase == "report" and step != config["updates"]:
                raise ValueError("Final holdout was opened early")
            for row in batch["rows"]:
                if row["behavior"]["model_sha256"] != train_hashes[step]:
                    raise ValueError(f"Batch lineage error {phase}/{step}/{root}")
                key = phase, step, root, row["mode"], row["replicate"]
                if key in envelope_keys:
                    raise ValueError("Duplicate public attempt")
                envelope_keys.add(key)
                rows_expected[key] = digest(row)
                for t in row["transitions"]:
                    i = t["action"]["index"]
                    assert t["observation"]["actions"][i] == t["action"]
                    assert not t["observation"]["relics"] and not any(t["observation"]["potions"])
                    assert (i == t["policy_argmax"] and t["behavior_logp"] == 0.) if row["mode"] == "greedy" else (
                        t["policy_logp"][i] == t["behavior_logp"])
                    transitions += 1
            if phase == "train":
                root_timings.append(dict(timing=batch["timing"], rows=[
                    {k: r[k] for k in ("timing", "inference_ms") if k in r} for r in batch["rows"]]))
    checks = sha256()
    with gzip.open(run / "public.jsonl.gz", "rb") as stream:
        for line in stream:
            checks.update(line)
            row = json.loads(line)
            key = row["split"], row["iteration"], row["root"], row["mode"], row["replicate"]
            if digest(row) != rows_expected.pop(key, None):
                raise ValueError("Exported row differs from committed ledger")
            if any(('"' + field + '":').encode() in line for field in (
                    "spec", "audit_stamp", "audit_action", "exact_root_sha256", "run_rng", "player_rng")):
                raise ValueError("Private information in public export")
    assert not rows_expected
    collect = sum(m["collect_seconds"] for m in by_step.values())
    optimize = sum(m["optimizer"]["seconds"] for m in by_step.values())
    durable = sum(json.loads(p.read_bytes())["seconds"] for p in (run / "checkpoint-timings").glob("*.json"))
    total = sum(statuses["train"].values())
    qualified = statuses["train"]["predicted_win"] + statuses["train"]["death"]
    cost = performance(root_timings)
    cost["inference_ms"] = quantiles([ms for b in root_timings for row in b["rows"] for ms in row["inference_ms"]])
    cost["warm_build_ms"] = quantiles([b["timing"]["initialize_ms"] for b in root_timings if b["timing"]["resident"]])
    cost["cold_build_ms"] = quantiles([b["timing"]["initialize_ms"] for b in root_timings if not b["timing"]["resident"]])
    save_json(output / "campaign.json", dict(identity=identity, checkpoints=seals, statuses=statuses,
              verified_menu_bindings=transitions,
              ledger=dict(rows=len(envelope_keys), sha256_uncompressed=checks.hexdigest()),
              independent_training_roots=len(root_timings), training_attempts=total, training_qualified=qualified,
              collect_seconds=collect, optimizer_seconds=optimize, checkpoint_seconds=durable,
              attempts_per_training_second=total / (collect + optimize + durable),
              qualified_per_training_second=qualified / (collect + optimize + durable),
              collection_attempts_per_second=total / collect,
              write_seconds=sum(m["audit_ledger_write_seconds"] for m in by_step.values()),
              pressure_metrics=cost,
              updates={u: {"optimizer": m["optimizer"], "statuses": m["metric"]["statuses"],
                           "environment_transitions": m["metric"]["env_replays"],
                           "collect_seconds": m["collect_seconds"]} for u, m in by_step.items()}))
    audit_hp(run, output / "hp-calibration.json")
    shutil.copyfile(run / "public.jsonl.gz", output / "public.jsonl.gz")
    for filename in ("run-status.json", "recovery.json"):
        if (run / filename).exists():
            shutil.copyfile(run / filename, output / filename)
    shutil.copytree(run / "reviews", output / "reviews")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "formal.json")
    args = p.parse_args()
    build(args.run.resolve(), args.output.resolve(), read(args.config))