"""Build sharded public/label views and audit coverage without exposing audit data to models."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
from hashlib import sha256
import itertools
import json
from pathlib import Path
from statistics import median

import numpy as np

from space import HERE, check_splits, digest, inventory, read
from engine import bank, model
from ls1_design import PROTOCOL
from semantics import serialize
import store


SCHEMA = "sts2.m1-ls2a.public-experience.v1"
SPLITS = ("train", "selection", "test", "development")


def semantic_cell(cell):
    outcome = cell["outcome"]
    return dict(profile=cell["profile"], outcome={
        k: v for k, v in outcome.items() if not k.endswith("_ms") and k != "peak_working_set_bytes"
    } | ({"attempts": [{k: v for k, v in a.items() if not k.endswith("_ms")}
                       for a in outcome["attempts"]]} if "attempts" in outcome else {}))


def source_rows(db, name):
    frozen = db.execute("SELECT manifest FROM plans WHERE plan=?", (name,)).fetchone()
    if frozen is None:
        raise ValueError("Unknown campaign")
    manifest = store.unpack(frozen[0])
    cases = {job["id"]: job["case"] for job in manifest["jobs"]}
    yield manifest
    for id_, item in store.results(db, name):
        yield cases[id_], item


def public_label(cell):
    tier, policy, cap = cell["profile"]
    result = cell["outcome"]
    positive = result["status"] == "qualified_win" or tier == "low" and result["status"] == "predicted_win"
    return dict(tier=tier, policy=policy, cap=cap, status=result["status"], evidence=cell["evidence"],
                transitions=result.get("transitions"), first_transitions=result.get("first_transitions"),
                locked=result.get("resource" if tier == "low" else "locked") if positive else None,
                route_risks=result.get("route_risks", []),
                attempts=[{k: a[k] for k in ("strategy", "status", "detail", "transitions", "allocated_limit",
                                             "verified_win", "locked", "first_cost")}
                          for a in result.get("attempts", [])])


def safe_candidate(label):
    if label["tier"] != "candidate" or label["route_risks"] or len(label["attempts"]) != 1:
        return None
    a = label["attempts"][0]
    if a["verified_win"]:
        locked = a["locked"]
        return .70 + .18 * locked["hp"] / locked["max_hp"] + .12 * (
            1 - a["first_cost"] / a["allocated_limit"])
    if a["status"] == "death" or a["status"] == "truncated" and a["detail"] in ("action_cap", "transition_cap"):
        return 0.
    return None


def examples(folder, split, mode):
    """Yield the LS1 trainer's (root, public, candidate, cap, utility) tuples."""
    if split not in SPLITS or mode not in ("card_id", "mechanics", "full_mechanics"):
        raise ValueError("Unknown split or input mode")
    for path in sorted(folder.glob(f"{split}-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["schema"] != SCHEMA or row["split"] != split:
                    raise ValueError("Export shard schema or partition differs")
                if mode == "full_mechanics" and row["encoding"] != "described":
                    continue
                for target in row["labels"]:
                    utility = safe_candidate(target)
                    if utility is not None:
                        yield row["root"], row["input"], target["policy"], target["cap"] // 2, utility


def describe(values):
    values = [v for v in values if v is not None]
    return dict(n=len(values), p50=median(values) if values else None,
                maximum=max(values, default=None))


def summarize(manifest, cases, batches, native):
    built = [(c, r) for c, r in cases if "exact" in r]
    unique = {}
    for c, r in built:
        previous = unique.setdefault(r["exact"], (c, r))
        if previous[0]["split"] != c["split"]:
            raise ValueError("Exact root crosses partitions")
    data = list(unique.values())
    check_splits([c | {"exact": r["exact"]} for c, r in data])
    cards = {a["card"]["spec_ref"] for _, r in data for a in r["public"]["identity_deck"]["cards"]}
    encounters = {(c["spec"]["act"], c["spec"]["encounter"]) for c, _ in data}
    character = Counter(c["spec"]["character"] for c, _ in data)
    coverage = {}
    for role, n in character.items():
        roots = [(c, r) for c, r in data if c["spec"]["character"] == role]
        catalog_cards = next(c["cards"] for c in native["characters"] if c["name"] == role)
        observed_cards = {a["card"]["spec_ref"] for _, r in roots for a in r["public"]["identity_deck"]["cards"]}
        coverage[role] = dict(roots=n, encounters=len({c["spec"]["encounter"] for c, _ in roots}),
                              cards=len(observed_cards), character_pool=len(catalog_cards),
                              identity_cards_missing_in_pool=sorted(observed_cards - {c["id"] for c in catalog_cards}),
                              solver_qualification=dict(Counter(r["qualification"]["solver"] for _, r in roots)))
    layers = defaultdict(list)
    support = Counter()
    changed = []
    low_to_high = Counter()
    disagreements = []
    for case, root in data:
        tiered = defaultdict(list)
        for cell in root["cells"]:
            label = public_label(cell)
            tier = label["tier"]
            layers[tier].append((label, cell))
            tiered[tier].append(label)
            if label["status"] in ("unsupported", "root_prediction_mismatch", "verification_failed", "rpc_error"
                                   ) or any(a["status"] == "unsupported" for a in label["attempts"]):
                support[label["status"]] += 1
        supported = [c for c in tiered["candidate"] if safe_candidate(c) is not None]
        if len(supported) >= 2:
            disagreements.append(len({c["status"] == "qualified_win" for c in supported}) > 1)
        if tiered["low"] and tiered["quality"]:
            light, deep = tiered["low"][0], tiered["quality"][0]
            low_to_high[light["status"] + " -> " + deep["status"]] += 1
        if tiered["standard"] and tiered["quality"]:
            a, b = tiered["standard"][0], tiered["quality"][0]
            changed.append(dict(old=a["status"], new=b["status"],
                                hp_delta=b["locked"]["hp"] - a["locked"]["hp"]
                                if a["locked"] and b["locked"] else None))
    catalog_encounters = {(a["act"], e["id"]) for a in native["acts"] for e in a["encounters"]}
    elapsed = sum(b["wall_seconds"] for b in batches)
    return dict(schema="sts2.m1-ls2a.summary.v1", manifest_sha256=digest(manifest),
                versions=manifest["versions"], planned=len(manifest["jobs"]), settled=len(cases),
                constructed=len(built), unique_roots=len(data), duplicate_roots=len(built)-len(data),
                recipes=len({c["recipe"] for c, _ in data}), families=len({c["family"] for c, _ in data}),
                seed_blocks=len({c["pair"] for c, _ in data}), native_histories=len({
                    c["history"] for c, _ in data if c["history"]}),
                sources=dict(Counter(c["natural_reachability"] for c, _ in data)),
                root_outcomes=dict(Counter(r["outcome"] for _, r in cases)),
                partitions=dict(Counter(c["split"] for c, _ in data)), characters=coverage,
                by_act=dict(Counter(c["spec"]["act"] for c, _ in data)),
                by_room=dict(Counter(c["room"] for c, _ in data)),
                encounters=len(encounters), catalog_encounters=len(catalog_encounters),
                missing_encounters=sorted(catalog_encounters-encounters),
                missing_characters=sorted(set(c["name"] for c in native["characters"]) - character.keys()),
                ascensions=dict(Counter(c["spec"]["ascension"] for c, _ in data)),
                hp_percent=describe(100*r["public"]["player"]["hp"]/r["public"]["player"]["max_hp"]
                                    for _, r in data),
                deck_size=describe(sum(e["count"] for e in r["public"]["identity_deck"]["cards"]) for _, r in data),
                unrepresented_relics=sorted(set(native["relics"]) -
                                            {e for _, r in data for e in r["public"]["relics"]}),
                unrepresented_potions=sorted(set(native["potions"]) -
                                            {e for _, r in data for e in r["public"]["potions"] if e}),
                unavailable_characters=native["unavailable_characters"],
                cards=len(cards), catalog_cards=len(inventory(native)), cards_outside_character_catalog=sorted(
                    cards-inventory(native).keys()),
                static_mechanisms=dict(Counter(tag for _, r in data for tag in r["mechanism_tags"])),
                enemy_types=dict(Counter(e["id"] for _, r in data for e in r["public"]["enemies"])),
                relics=dict(Counter(e for _, r in data for e in r["public"]["relics"])),
                potions=dict(Counter(e for _, r in data for e in r["public"]["potions"] if e)),
                encoding_gaps=dict(Counter(g for _, r in data for g in r["encoding_gaps"])),
                solver_status=dict(Counter(r["qualification"]["solver"] for _, r in data)),
                support_issues=dict(support), l3=0,
                predicted_replay_transitions=sum(a["transitions"] or 0 for rows in layers.values() for a, _ in rows),
                layers={tier: dict(cells=len(rows), roots=sum(any(c["profile"][0] == tier for c in r["cells"])
                                                             for _, r in data),
                                   statuses=dict(Counter(a["status"] for a, _ in rows)),
                                   transitions=sum(a["transitions"] or 0 for a, _ in rows),
                                   wall_ms=describe(c["wall_ms"] for _, c in rows),
                                   hot_ms=describe(c["outcome"].get("hot_ms") for _, c in rows))
                        for tier, rows in layers.items()},
                candidates=dict(comparable_roots=len(disagreements), differing_win=sum(disagreements)),
                low_to_quality=dict(low_to_high),
                paired_budgets=dict(roots=len(changed), outcomes=dict(Counter(
                    a["old"]+" -> "+a["new"] for a in changed)), hp_delta=describe(a["hp_delta"] for a in changed),
                                    hp_improved=sum((a["hp_delta"] or 0)>0 for a in changed),
                                    hp_reduced=sum((a["hp_delta"] or 0)<0 for a in changed)),
                batches=batches, elapsed_seconds=elapsed, roots_per_hour=len(data)*3600/elapsed if elapsed else None,
                root_wall_ms=describe(r["wall_ms"] for _, r in data),
                initialize_ms=describe(r["root_timing"]["initialize_ms"] for _, r in data)), data


def write_shard(path, rows):
    """Write an immutable, deterministic JSONL shard and return its byte checksum."""
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=3) as stream:
            for row in rows:
                stream.write((serialize(row) + "\n").encode("utf-8"))
    return sha256(path.read_bytes()).hexdigest()


def export(directory, name, destination, shard_size):
    with closing(store.open_store(directory / "search.sqlite")) as db:
        rows = source_rows(db, name)
        manifest = next(rows)
        batches = [store.unpack(row[0]) for row in db.execute("SELECT data FROM batches WHERE plan=? ORDER BY number",
                                                            (name,))]
        summary, data = summarize(manifest, list(rows), batches, read(directory / "catalog.json"))
        summary["attempts"] = dict(db.execute(
            "SELECT state,COUNT(*) FROM attempts WHERE plan=? GROUP BY state", (name,)).fetchall())
        summary["reserved_first_attempt_replays"] = sum(j["reserved"] for j in manifest["jobs"])
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "manifest.audit.json.gz").write_bytes(store.pack(manifest))
    counts = Counter()
    shard_hashes = {}
    for split in SPLITS:
        rows = (dict(schema=SCHEMA, root=r["exact"], split=split, input=r["public"],
                     encoding=r["qualification"]["encoding"],
                     labels=[public_label(cell) for cell in r["cells"]])
                for c, r in data if c["split"] == split)
        part = 0
        while chunk := list(itertools.islice(rows, shard_size)):
            path = destination / f"{split}-{part:05d}.jsonl.gz"
            shard_hashes[path.name] = write_shard(path, chunk)
            counts[split] += len(chunk)
            part += 1
    compatibility = {}
    for split in SPLITS:
        selected = list(examples(destination, split, "mechanics"))
        for mode in ("card_id", "mechanics"):
            sample = selected[:64]
            if sample:
                for _, x in model.arrays(sample, mode, PROTOCOL["training"]):
                    params = model.network["init"](x, PROTOCOL["training"]["hidden"], 17)
                    if not np.isfinite(model.network["forward"](params, x)[0]).all():
                        raise ValueError("Existing LS1 trainer could not consume the export")
        compatibility[split] = dict(candidate_rows=len(selected), candidate_roots=len({e[0] for e in selected}),
                                    feature_rows_verified=min(64, len(selected)))
    summary["export"] = dict(schema=SCHEMA, roots=dict(counts), ls1_batch_compatibility=compatibility,
                             shard_count=len(shard_hashes), sha256=shard_hashes)
    bank.atomic(destination / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--name", default="main")
    parser.add_argument("--shard-size", default=128, type=int, choices=range(1, 4097), metavar="N")
    args = parser.parse_args()
    result = export(args.directory, args.name, args.destination, args.shard_size)
    print(result["unique_roots"], "unique roots", result["export"])
