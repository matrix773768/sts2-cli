"""Build immutable feature shards from checksummed public trajectory records."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import random
from time import perf_counter

import numpy as np

from features import CATALOG_PATH, Encoder, HERE, SOURCE_HASHES, load_vocabulary
from labels import labels, scoped_order

import sys
sys.path.append(str(HERE.parent / "m1-pre0"))
from dataset import batches, digest

ROWS_PER_SHARD = 2048
VARIABLE = {"cards", "instances", "mods", "zones", "enemies", "actions", "refs"}


def checksum(path):
    sha = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(2**20):
            sha.update(chunk)
    return sha.hexdigest()


def collate(rows):
    first = rows[0]
    arrays = {}
    for key, value in first.items():
        if key not in VARIABLE:
            arrays[key] = np.asarray([row[key] for row in rows])
            continue
        n = max(len(row[key]) for row in rows)
        data = np.zeros((len(rows), n, *value.shape[1:]), dtype=value.dtype)
        for index, row in enumerate(rows):
            item = row[key]
            data[index, :len(item)] = item
        arrays[key] = data
    arrays["mask"] = np.arange(arrays["actions"].shape[1])[None, :] < np.asarray(
        [len(row["actions"]) for row in rows])[:, None]
    return arrays


def convert(trajectory, encoder, per_trajectory, source):
    length = trajectory["length"]
    rng = random.Random(trajectory["id"])
    bins = min(length, per_trajectory)
    selected = {rng.randrange(i*length//bins, (i+1)*length//bins) for i in range(bins)}
    memory = encoder.initial_history()
    extra = False
    for index, step in enumerate(trajectory["steps"]):
        obs, action = step["observation"], step["action"]
        order = scoped_order(obs)
        if index in selected or order and not extra:
            yield encoder.encode(obs, memory) | labels(trajectory, index, order, source)
            extra |= bool(order)
        memory = encoder.update(memory, obs, action)


def prepare(output, files, per_trajectory):
    if per_trajectory < 1:
        raise ValueError("Positive decision sample count required")
    output.mkdir(exist_ok=True)
    vocabulary = load_vocabulary(files)
    encoder = Encoder(vocabulary)
    identity = dict(schema="sts2.pre1.features.v1", vocabulary=vocabulary,
                    data={str(path.resolve()): checksum(path) for path in files},
                    per_trajectory=per_trajectory, n2e_sha256=checksum(CATALOG_PATH),
                    source={name: checksum(HERE/name) for name in ("prepare.py","features.py","labels.py")})
    identity["sha256"] = digest(identity)
    identity_path = output / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_bytes()) != identity:
        raise ValueError("Feature cache identity changed")
    identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_bytes())
        if manifest["identity"] != identity:
            raise ValueError("Existing manifest does not match")
        return manifest
    start = perf_counter()
    buffers = {key: [] for key in ("train","validation","evaluation")}
    shards = {key: [] for key in buffers}
    stats = Counter()
    families = {}
    compositions = {}
    seen = set()

    def flush(split):
        rows = buffers[split]
        if not rows:
            return
        path = output / f"{split}-{len(shards[split]):04d}.npz"
        arrays = collate(rows)
        # Normalize target dtypes once for GPU transfer.
        for key in ("delta", "order", "outcome"):
            arrays[key] = arrays[key].astype(np.float32)
        temp = path.with_suffix(".partial")
        with temp.open("wb") as handle:
            np.savez(handle, **arrays)
        temp.replace(path)
        shards[split].append(dict(name=path.name, rows=len(rows), sha256=checksum(path)))
        rows.clear()

    for path in files:
        for group in batches(path, size=64):
            for trajectory in group:
                if trajectory["id"] in seen:
                    raise ValueError("Repeated task ID in training sources")
                seen.add(trajectory["id"])
                if trajectory["evidence"] != "prediction_only" or trajectory["root"]["character"] != "Ironclad":
                    raise ValueError("Unexpected training trajectory qualifications")
                split = trajectory["split"]
                if families.setdefault(trajectory["family"], split) != split:
                    raise ValueError("Deck family crosses splits")
                composition = tuple(sorted(card["id"] for card in trajectory["root"]["deck"]))
                if compositions.setdefault(composition, split) != split:
                    raise ValueError("Identical deck composition crosses splits")
                source = SOURCE_HASHES.index(trajectory["behavior"]["model_sha256"])
                stats[f"{split}_{source}_trajectories"] += 1
                for row in convert(trajectory, encoder, per_trajectory, source):
                    stats[f"{split}_{source}_rows"] += 1
                    stats[f"{split}_relation"] += int(row["order_mask"])
                    stats[f"{split}_delta"] += int(row["delta_mask"])
                    buffers[split].append(row)
                    if len(buffers[split]) == ROWS_PER_SHARD:
                        flush(split)
        print(path, dict(stats), flush=True)
    for split in buffers:
        flush(split)
    result = dict(identity=identity, stats=stats, shards=shards,
                  deck_families=len(families), seconds=perf_counter()-start)
    temp = manifest_path.with_suffix(".partial")
    temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temp.replace(manifest_path)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("datasets", type=Path, nargs="+")
    parser.add_argument("--decisions", type=int, default=6)
    args = parser.parse_args()
    result = prepare(args.output, args.datasets, args.decisions)
    print(json.dumps(result["stats"], indent=2))
