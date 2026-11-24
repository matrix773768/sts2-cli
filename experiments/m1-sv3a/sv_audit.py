"""Audit partitioning, historical reruns and realized training exposure."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from sv_data import ROOT, db_for, decoded, digest, write_json
from sv_train import sample_rows


def terminal_stats(path):
    counts = defaultdict(Counter)
    hp_bins = defaultdict(Counter)
    with gzip.open(path / "terminals.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            name = row["split"]
            group = counts[name]
            group["trajectories"] += 1
            group["decisions"] += row["decisions"]
            group[row["status"]] += 1
            group["hp999"] += row["root_hp"] == 999
            group["max_hp_changed"] += row["final"]["max_hp"] != row["root_max_hp"]
            group["final_hp_above_start"] += row["final"]["hp"] > row["root_hp"]
            hp_bins[name][str(row["final"]["hp"])] += 1
    return counts, hp_bins


def split_and_overlap(manifest):
    ownership = {}
    signatures = {}
    duplicate = Counter()
    family_split = Counter()
    for label in ("pre0b", "pre0", "p0", "teacher", "structured", "a2_spike"):
        item = manifest["data"][label]
        with closing(db_for(ROOT / item["path"])) as db:
            query = """
              SELECT t.split,t.sha,t.payload,p.recipe FROM trajectories t JOIN private_tasks p USING(id)
              WHERE t.complete=1 ORDER BY t.ordinal
            """
            for split, expected, blob, recipe in db.execute(query):
                spec = json.loads(recipe)
                family = digest(sorted(card["id"] for card in spec["deck"]))
                if family not in ownership:
                    ownership[family] = split
                    family_split[split] += 1
                elif ownership[family] != split:
                    raise ValueError("A deck family crosses the sealed split")
                if label not in ("pre0b", "pre0"):
                    continue
                identity = (item["behavior"], item["policy_seed"], sha256(recipe).hexdigest())
                if split == "evaluation":
                    if identity in signatures:
                        duplicate["sealed_overlap_metadata_only"] += 1
                    signatures[identity] = None
                    continue
                row = decoded(expected, blob)
                path = digest([(step["observation"],step["action"]) for step in row["steps"]])
                terminal = digest([row["status"], row["terminal"]])
                if identity in signatures:
                    old_path, old_terminal = signatures[identity]
                    duplicate["train_validation_overlap"] += 1
                    duplicate["same_observations_and_actions"] += old_path == path
                    duplicate["same_terminal"] += old_terminal == terminal
                signatures[identity] = (path, terminal)
    return family_split, duplicate


def exposures(manifest, root):
    keys = []
    for item in manifest["shards"]["train"]:
        with np.load(root / item["name"], allow_pickle=False) as f:
            keys.append({"trajectory": f["trajectory"]})
    cfg = manifest["config"]
    observed = {}
    for seed in cfg["seeds"]:
        used = [np.zeros(len(item["trajectory"]), dtype=bool) for item in keys]
        for epoch in range(1, cfg["epochs"] + 1):
            rng = np.random.default_rng([seed, epoch])
            for index in rng.permutation(len(keys)):
                rows, _ = sample_rows(keys[index], cfg["epoch_draws"], rng)
                used[index][rows] = True
        observed[str(seed)] = sum(int(sel.sum()) for sel in used)
    return observed


def audit_pilots(manifest):
    """Inventory smoke and throughput runs without reading sealed payloads."""
    accepted = set()
    canonical = {ROOT / row["path"] for row in manifest["data"].values()}

    def roots(path):
        with closing(db_for(path)) as db:
            meta = json.loads(db.execute("SELECT json FROM manifest").fetchone()[0])
            prefix = (meta["behavior"], meta["config"]["policy_seed"])
            rows = [(split, (*prefix, sha256(recipe).hexdigest()))
                    for split, recipe in db.execute("""
                        SELECT t.split,p.recipe FROM trajectories t JOIN private_tasks p USING(id)
                        WHERE t.complete=1
                    """)]
        return meta, rows

    for path in canonical:
        _, rows = roots(path)
        accepted.update(identity for _, identity in rows)
    outputs, remaining = {}, set()
    for directory in sorted((ROOT / "logs").glob("m1-pre*")):
        path = directory / "dataset.sqlite"
        if path in canonical or not path.is_file():
            continue
        meta, rows = roots(path)
        known = sum(identity in accepted for _, identity in rows)
        remaining.update(identity for _, identity in rows if identity not in accepted)
        outputs[directory.name] = dict(complete=len(rows), formal_overlap=known,
            unique_recipe_count=len({identity for _, identity in rows}),
            recipe=meta["config"]["version"], behavior=meta["behavior"],
            distribution=dict(Counter(split for split, _ in rows)))
    return dict(pilot_ledgers=outputs, distinct_nonformal_recipe_behaviors=len(remaining),
                policy="Smoke, throughput and recovery ledgers are audit-only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pilots", action="store_true")
    args = parser.parse_args()
    identity = json.loads((args.data / "manifest.json").read_bytes())
    if args.pilots:
        report = audit_pilots(identity)
        write_json(args.output, report)
        print(len(report["pilot_ledgers"]), report["distinct_nonformal_recipe_behaviors"], flush=True)
        raise SystemExit(0)
    split, overlap = split_and_overlap(identity)
    count, terminal = terminal_stats(args.data)
    report = dict(families=split, overlap=overlap, retained=count, raw_terminal_hp=terminal,
                  unique_training_decisions=exposures(identity, args.data))
    write_json(args.output, report)
    print({key: value for key, value in report.items() if key != "raw_terminal_hp"}, flush=True)
