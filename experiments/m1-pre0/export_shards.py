"""Export public, checksummed JSONL gzip shards from a finished PRE0 dataset."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path

from dataset import batches, encode


def publish(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing export differs at {path}")
        return
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(data)
    partial.replace(path)


def export(source, output, split, size):
    output.mkdir(parents=True, exist_ok=True)
    shards = []
    for number, rows in enumerate(batches(source, size=size, split=split)):
        data = gzip.compress(b"".join(encode(row) + b"\n" for row in rows), compresslevel=3, mtime=0)
        name = f"shard-{number:06d}.jsonl.gz"
        publish(output / name, data)
        shards.append(dict(name=name, sha256=sha256(data).hexdigest(), rows=len(rows)))
    manifest = dict(contract="sts2.m1-pre0.public-shards.v1", split=split, shard_size=size,
                    source_sha256=sha256_file(source), rows=sum(shard["rows"] for shard in shards),
                    shards=shards)
    publish(output / "manifest.json", encode(manifest))
    return manifest


def sha256_file(path):
    hash_ = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(2**20):
            hash_.update(chunk)
    return hash_.hexdigest()


def read_shards(output):
    manifest = json.loads((output / "manifest.json").read_bytes())
    if manifest["contract"] != "sts2.m1-pre0.public-shards.v1":
        raise ValueError("Unexpected shard contract")
    for number, shard in enumerate(manifest["shards"]):
        if shard["name"] != f"shard-{number:06d}.jsonl.gz":
            raise ValueError("Unexpected shard name")
        raw = (output / shard["name"]).read_bytes()
        if sha256(raw).hexdigest() != shard["sha256"]:
            raise ValueError(f"Damaged shard {shard['name']}")
        records = [json.loads(row) for row in gzip.decompress(raw).splitlines()]
        if len(records) != shard["rows"]:
            raise ValueError("Shard row count mismatch")
        yield records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split", choices=("train", "validation", "evaluation"))
    parser.add_argument("--size", type=int, default=256)
    args = parser.parse_args()
    print(json.dumps(export(args.dataset, args.output, args.split, args.size), indent=2))
