"""Append labeled experience without modifying the frozen historical cache."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
import os
from pathlib import Path

from sv_data import Encoder, Shards, checksum, db_for, digest, encode, examples, policy_key, write_json


def extend(source, output, journal, roots, mix=None):
    from sv_eval import load_rows
    original = json.loads((source / "manifest.json").read_bytes())
    base = original["config"]
    frozen = json.loads(roots.read_bytes())
    with closing(db_for(journal / "results.sqlite")) as db:
        contract = json.loads(db.execute("SELECT json FROM contract").fetchone()[0])
    if frozen.get("purpose") != "experience" or contract["purpose"] != "experience":
        raise ValueError("Development or confirmation experience is ineligible for training")
    if checksum(roots) != contract["manifest"]:
        raise ValueError("Experience root manifest changed")
    attempts = load_rows(journal)
    if len(attempts) != len(frozen["jobs"]):
        raise ValueError("Incomplete experience ledger")
    rows = [item["row"] for item in attempts if item["row"]["complete"]]
    if not rows or any(row["evidence"] != "prediction_only" or row["split"] != "train" for row in rows):
        raise ValueError("Invalid new value trajectory qualification")
    for item, job in zip(attempts, frozen["jobs"], strict=True):
        expected = {key: value for key, value in job[1].items() if key != "seed"}
        if item["row"]["root"] != expected:
            raise ValueError("Experience record does not match its frozen root")
    keys = {policy_key(row["behavior"]) for row in rows}
    identity, = keys
    policies = original["policies"]
    if identity in policies or len(policies) >= base["policy_slots"]:
        raise ValueError("Experience policy already present or reserved slots exhausted")
    output.mkdir(parents=True, exist_ok=False)
    encoder = Encoder(original["vocabulary"])
    shards = Shards(output)
    offset = sum(s["retained"].get("train", 0) + s["retained"].get("validation", 0)
                 for s in original["source_stats"].values())
    retained = Counter()
    with gzip.open(output / "terminals.jsonl.gz", "wb", compresslevel=3) as result:
        for trajectory, row in enumerate(rows, offset):
            block = list(examples(row, encoder, base, len(policies), trajectory, base["per_trajectory"]))
            shards.add("train", block)
            retained["train"] += 1
            retained["train_rows"] += len(block)
            retained[row["status"]] += 1
            result.write(encode(dict(trajectory=trajectory, id=row["id"], behavior=row["behavior"],
                status=row["status"], final=row["terminal"], cumulative_loss=row["cumulative_loss"])) + b"\n")
    shards.flush("train")
    groups = {}
    for phase, group in original["shards"].items():
        groups[phase] = [entry | {"name": Path(os.path.relpath(source / entry["name"], output)).as_posix()}
                         for entry in group[:mix]] + shards.paths[phase]
    extension = dict(base=checksum(source/"manifest.json"), roots=checksum(roots),
        journal=checksum(journal/"results.sqlite"), episodes=len(rows), attempts=len(attempts),
        outcomes=Counter(item["row"]["status"] for item in attempts), mix=mix)
    result = original | dict(policies=[*policies, identity], shards=groups,
        source_stats=original["source_stats"] | {f"experience_{digest(identity)[:16]}": {"retained": retained}},
        extensions=[*original.get("extensions", []), extension],
        terminals_sha256=checksum(output/"terminals.jsonl.gz"))
    write_json(output / "manifest.json", result)
    print(extension, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("historical", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("journal", type=Path)
    cli.add_argument("roots", type=Path)
    cli.add_argument("--mix-shards", type=int)
    args = cli.parse_args()
    if args.mix_shards is not None and args.mix_shards < 1:
        cli.error("mix-shards must be positive")
    extend(args.historical.resolve(), args.output.resolve(), args.journal.resolve(),
           args.roots.resolve(), args.mix_shards)
