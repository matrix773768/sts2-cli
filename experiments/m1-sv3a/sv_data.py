"""Audit historical trajectories and freeze trajectory-balanced public-value tensors."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import sqlite3
import sys
from time import perf_counter

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRE1 = HERE.parent / "m1-pre1"
sys.path.insert(0, str(PRE1))
sys.path.append(str(HERE.parent / "m1-pre0"))
from dataset import digest, encode
from features import CATALOG_PATH, Encoder, RULES, SOURCE_HASHES, variant
from prepare import checksum, collate

PHASES = ("train", "validation")
ROOMS = ("Monster", "Elite", "Boss")
POLICIES = ("P0", "A2")
FEATURES = ("cards", "instances", "mods", "zones", "enemies", "actions", "refs",
            "player", "history", "choice", "mask")
EFFECTS = (frozenset(("Draw",)), frozenset(("GainEnergy", "IncreaseEnergy")))


def config():
    return json.loads((HERE / "config.json").read_bytes())


def db_for(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def write_json(path, data):
    temporary = path.with_suffix(".partial")
    temporary.write_bytes(encode(data) + b"\n")
    temporary.replace(path)


def decoded(expected, blob):
    data = gzip.decompress(blob)
    if sha256(data).hexdigest() != expected:
        raise ValueError("Trajectory checksum mismatch")
    return json.loads(data)


def policy_key(behavior):
    return "|".join(behavior[k] for k in ("model", "model_sha256", "mode"))


def outcome(row, bins):
    terminal = row["terminal"]
    hp, max_hp = terminal["hp"], terminal["max_hp"]
    if max_hp <= 0 or row["status"] not in ("predicted_win", "death"):
        raise ValueError("Invalid complete outcome")
    if row["status"] == "death":
        if hp != 0:
            raise ValueError("Death with positive HP")
        return 0
    if not 0 < hp <= max_hp:
        raise ValueError("Victory with invalid HP")
    return 1 + round((bins - 1) * hp / max_hp)


def mechanics(obs):
    flags = 0
    for card in obs["hand"]:
        for flag, wanted in enumerate(EFFECTS):
            if any(node["kind"] in wanted for node in variant(card["id"], card["upgrade"])[1].get("effects", ())):
                flags |= 1 << flag
    return flags


def examples(row, encoder, cfg, policy, trajectory, limit):
    steps = row["steps"]
    terminal = row["terminal"]
    result = outcome(row, cfg["hp_bins"])
    rng = random.Random(row["id"])
    count = min(len(steps), limit)
    chosen = {rng.randrange(i * len(steps) // count, (i + 1) * len(steps) // count) for i in range(count)}
    history = encoder.initial_history()
    root = row["root"]
    for index, step in enumerate(steps):
        obs, action = step["observation"], step["action"]
        if (not step["advanced"] or step["position"] != index or obs["actions"][action["index"]] != action):
            raise ValueError("Invalid trajectory decision")
        if index in chosen:
            group = np.array([root["act"], ROOMS.index(row["room"]), root["hp"],
                              obs["hp"], obs["max_hp"], obs["turn"], len(obs["hand"]),
                              obs["energy"], mechanics(obs), obs["decision"]["phase"] == "choice"], dtype=np.int16)
            yield encoder.encode(obs, history) | dict(policy=np.int16(policy), chosen=np.int16(action["index"]),
                cls=np.int16(result), final_hp=np.int16(terminal["hp"]), final_max=np.int16(terminal["max_hp"]),
                max_delta=np.float32((terminal["max_hp"] - obs["max_hp"]) / 25),
                group=group, trajectory=np.int32(trajectory), old_logp=np.float32(
                    step["behavior_logp"] if math.isfinite(step.get("behavior_logp") or 0.) else 0.),
                weight=np.float32(1 / count))
        history = encoder.update(history, obs, action)


class Shards:
    def __init__(self, root):
        self.root = root
        self.paths = {key: [] for key in PHASES}
        self.rows = {key: [] for key in PHASES}

    def add(self, split, encoded):
        self.rows[split].extend(encoded)
        if len(self.rows[split]) >= 4096:
            self.flush(split)

    def flush(self, split):
        rows = self.rows[split]
        if not rows:
            return
        path = self.root / f"{split}-{len(self.paths[split]):04}.npz"
        arrays = collate(rows)
        with path.with_suffix(".partial").open("wb") as stream:
            np.savez(stream, **arrays)
        path.with_suffix(".partial").replace(path)
        self.paths[split].append(dict(name=path.name, rows=len(rows), sha256=checksum(path)))
        rows.clear()


def prepare(output, decisions=None):
    import torch
    cfg = config()
    if decisions is not None:
        cfg["per_trajectory"] = decisions
    output.mkdir(parents=True, exist_ok=False)
    checkpoint = ROOT / cfg["pre1"]
    weights = torch.load(checkpoint, map_location="cpu", weights_only=True)
    vocabulary = weights["vocabulary"]
    encoder = Encoder(vocabulary)
    shards = Shards(output)
    stats, manifests, families, origins = {}, {}, {}, {}
    decks = set()
    behaviors = [f"nosl3c.hp-loss-actor-critic.v4|{key}|sample" for key in SOURCE_HASHES]
    all_times = perf_counter()
    trajectory = -1
    with gzip.open(output / "terminals.jsonl.gz", "wb", compresslevel=3) as journal:
        for label, relative in cfg["sources"].items():
            path = ROOT / relative
            with closing(db_for(path)) as db:
                manifest_sha, manifest_raw = db.execute("SELECT sha,json FROM manifest").fetchone()
                if sha256(manifest_raw).hexdigest() != manifest_sha:
                    raise ValueError(f"Invalid source manifest {label}")
                manifest = json.loads(manifest_raw)
                manifests[label] = dict(path=relative, sha256=checksum(path), manifest_sha256=manifest_sha,
                                        behavior=manifest["behavior"], recipe=manifest["config"]["version"],
                                        policy_seed=manifest["config"]["policy_seed"])
                source = stats[label] = {"counts": Counter(), "outcomes": Counter(), "coverage": Counter(),
                                         "terminal_hp": Counter(), "retained": Counter(), "duplicates": Counter()}
                for split, complete, n in db.execute("SELECT split,complete,count(*) FROM trajectories GROUP BY split,complete"):
                    source["counts"][f"{split}:{complete}"] = n
                rows = db.execute("""
                    SELECT t.sha,t.payload,p.recipe FROM trajectories t LEFT JOIN private_tasks p USING(id)
                    WHERE t.complete=1 AND t.split IN ('train','validation') ORDER BY t.ordinal
                """)
                for expected, blob, recipe in rows:
                    row = decoded(expected, blob)
                    if recipe is None or row["evidence"] != "prediction_only" or row["root"]["character"] != "Ironclad":
                        raise ValueError("Ineligible trajectory in complete historical corpus")
                    root, split = row["root"], row["split"]
                    behavior = policy_key(row["behavior"])
                    policy = behaviors.index(behavior)
                    if row["behavior"]["model_sha256"] != manifest["behavior"]:
                        raise ValueError("Recorded policy drift")
                    family = tuple(sorted(card["id"] for card in root["deck"]))
                    owner = families.setdefault(family, split)
                    if owner != split:
                        raise ValueError("Unupgraded deck family crosses train and validation")
                    recipe_sha = sha256(recipe).hexdigest()
                    identity = (recipe_sha, behavior, manifest["config"]["policy_seed"])
                    original = origins.get(identity)
                    source["outcomes"][row["status"]] += 1
                    source["counts"]["decisions"] += row["length"]
                    source["counts"]["hp999"] += root["hp"] == 999
                    source["coverage"][f'{root["act"]}:{root["encounter"]}'] += 1
                    source["terminal_hp"][str(row["terminal"]["hp"])] += 1
                    if original is not None:
                        source["duplicates"][original] += 1
                        continue
                    origins[identity] = label
                    decks.add(family)
                    trajectory += 1
                    if row["length"] != len(row["steps"]) or not row["length"]:
                        raise ValueError("Invalid complete trajectory length")
                    encoded = list(examples(row, encoder, cfg, policy, trajectory, cfg["per_trajectory"]))
                    shards.add(split, encoded)
                    source["retained"][split] += 1
                    source["retained"][f"{split}_rows"] += len(encoded)
                    journal.write(encode(dict(trajectory=trajectory, id=row["id"], source=label, behavior=row["behavior"],
                        split=split, root_hp=root["hp"], root_max_hp=root["max_hp"], status=row["status"],
                        final=row["terminal"], cumulative_loss=row.get("cumulative_loss"),
                        cumulative_healing=row.get("cumulative_healing"), decisions=row["length"])) + b"\n")
            print(label, dict(source["retained"]), dict(source["duplicates"]), flush=True)
    for split in PHASES:
        shards.flush(split)
    identity = dict(schema=cfg["schema"], config=cfg, vocabulary=vocabulary, policies=behaviors,
                    data=manifests, pre1_sha256=checksum(checkpoint), feature_sha256=checksum(PRE1 / "features.py"),
                    n2e_sha256=checksum(CATALOG_PATH), implementation=checksum(Path(__file__)),
                    source_stats=stats, deck_families=len(decks), sealed_split="evaluation metadata only",
                    shards=shards.paths, terminals_sha256=checksum(output / "terminals.jsonl.gz"),
                    seconds=perf_counter() - all_times)
    write_json(output / "manifest.json", identity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--decisions", type=int)
    args = parser.parse_args()
    prepare(args.output, args.decisions)
