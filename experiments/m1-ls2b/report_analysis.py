"""Export public, learning and audit views; paired quality/cost statistics from immutable rows."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
from pathlib import Path
from statistics import mean, median

from campaign import ARMS, context, digest, immutable, read
from export_data import source_rows, write_shard
from space import check_splits
import store


def eligible(row):
    return row["status"] == "qualified_win" and not row["risks"] and row["locked"]["hp"] >= 1


def numbers(values):
    data = [v for v in values if v is not None]
    return dict(n=len(data), mean=mean(data) if data else None, p50=median(data) if data else None,
                total=sum(data))


def differs(left, right):
    """A shorter matching prefix alone is inconclusive."""
    return any(x != y for x, y in zip(left, right))


def prefix_length(path, known):
    longest = 0
    for other in known:
        length = 0
        for a, b in zip(path, other):
            if a != b:
                break
            length += 1
        longest = max(longest, length)
    return longest


def arm_stats(rows):
    wins = [row for row in rows if eligible(row)]
    attempts = [a for row in rows for a in row["attempts"]]
    repairs = [a for a in attempts if a["parent_strategy"]]
    # Parent comparisons must remain within an exact root and cell.
    repair_changes = repair_wins = repair_known = overlap = comparable = 0
    identical = finished = 0
    for row in rows:
        seen = []
        complete = set()
        parents = {}
        for a in row["attempts"]:
            path = a["path"]
            if a["status"] in ("death", "qualified_win"):
                signature = (a["status"], tuple(path))
                identical += signature in complete
                finished += 1
                complete.add(signature)
            if path:
                overlap += prefix_length(path, seen)
                comparable += len(path)
                seen.append(path)
            if a["parent_strategy"]:
                parent = parents[a["parent_strategy"]]
                repair_changes += differs(path, parent["path"])
                repair_known += bool(path and parent["path"])
                repair_wins += a["status"] == "qualified_win" and not a["risks"]
            parents[a["strategy_hash"]] = a
    return dict(cells=len(rows), wins=len(wins), status=dict(Counter(r["status"] for r in rows)),
                first_replays=numbers(r["first_replays"] for r in wins),
                first_ms=numbers(r["first_ms"] for r in wins),
                replays=numbers(r.get("transitions") for r in rows), wall_ms=numbers(r["wall_ms"] for r in rows),
                hp=numbers(r["locked"]["hp"] for r in wins), gold=numbers(r["locked"]["gold"] for r in wins),
                potions=numbers(sum(p is not None for p in r["locked"]["potions"]) for r in wins),
                risk_wins=sum(r["status"] == "qualified_win" and bool(r["risks"]) for r in rows),
                generated=sum(r.get("generated", 0) for r in rows), duplicates=sum(r.get("duplicates", 0) for r in rows),
                generation_ms=numbers(r.get("generation_ms") for r in rows),
                inference_ms=numbers(r.get("inference_ms") for r in rows), repair_ms=numbers(r.get("repair_ms") for r in rows),
                attempts=len(attempts), attempt_status=dict(Counter(a["status"] for a in attempts)),
                repairs=len(repairs), repair_wins=repair_wins, repair_path_changed=repair_changes,
                repair_nonempty_pairs=repair_known, shared_prefix_actions=overlap, completed_actions=comparable,
                equivalent_terminal_paths=identical, terminal_paths=finished,
                switches=sum(len({step["phase"] for step in a["trace"]}) > 1 for a in attempts))


def learning_root(case, item, phase):
    cells = []
    for c in item["cells"]:
        out = c["outcome"]
        rows = []
        for a in out["attempts"]:
            rows.append(dict(input=dict(strategy_spec=a["strategy_spec"]), strategy_hash=a["strategy_hash"],
                parent_strategy=a["parent_strategy"], repair_operation=a["repair_operation"],
                repair_depth=a["repair_depth"], generator_version=a["generator_version"], search_budget=a["allocated"],
                label={k: a.get(k) for k in ("status", "resource", "failure_feedback", "transitions",
                                              "remaining", "initial_enemy_hp", "verification", "risks")}))
        cells.append(dict(profile=c["profile"], attempts=rows,
                          outcome={k: out.get(k) for k in ("status", "first_replays", "first_ms", "locked", "risks",
                                                           "transitions", "wall_ms")}))
    return dict(schema="ls2b.experience.v1", group=case["id"], split=phase, source=case["source"],
                natural_reachability=case["natural_reachability"], public_context=item["public"],
                encoding_gaps=item["gaps"], evidence_level=item["evidence"], cells=cells)


def training_examples(path):
    """Group key, public proposal input, post-execution target. Previous feedback is a separate repair view."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            root = json.loads(line)
            if root["schema"] != "ls2b.experience.v1":
                raise ValueError("Experience schema mismatch")
            for c in root["cells"]:
                parents = {}
                for a in c["attempts"]:
                    parent = parents.get(a["parent_strategy"])
                    if a["repair_depth"] and parent is None:
                        raise ValueError("Repair parent missing from group")
                    features = dict(context=context(root["public_context"]), strategy_spec=a["input"]["strategy_spec"],
                                    search_budget=a["search_budget"])
                    if parent is not None:
                        features["research_repair"] = dict(parent=parent["input"]["strategy_spec"],
                            observed=parent["label"]["failure_feedback"], edit=a["repair_operation"])
                    yield root["group"], features, a["label"]
                    parents[a["strategy_hash"]] = a


def fit_rows(path):
    """Reproduce the frozen fit from grouped public shards, without the SQLite audit ledger."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["schema"] != "ls2b.experience.v1" or row["split"] != "development":
                raise ValueError("Expected open development supervision")
            for c in row["cells"]:
                yield dict(split=row["split"], root=row["group"], context=context(row["public_context"]),
                           attempts=[a["label"] | a["input"] | dict(strategy_hash=a["strategy_hash"],
                                     allocated=a["search_budget"]) for a in c["attempts"]])


def compare(results, cap, mode):
    counts = Counter()
    changes, hp_delta = [], []
    witnesses = {}
    for rid, grid in results.items():
        base, cur = grid["baseline", cap], grid[mode, cap]
        a, b = eligible(base), eligible(cur)
        kind = ("both" if a and b else "only_new" if b else "only_baseline" if a else "neither")
        counts[kind] += 1
        if b and not a:
            witnesses.setdefault("only_new", rid)
        if a and b:
            same = base["seed_key"] == cur["seed_key"]
            counts["same_first_route" if same else "different_first_route"] += 1
            for label, measure in (("replays", "first_replays"), ("ms", "first_ms")):
                if same and cur[measure] < base[measure]:
                    counts["same_first_earlier_"+label] += 1
            hp_delta.append(cur["locked"]["hp"] - base["locked"]["hp"])
        controls = [v["path"] for (policy, _), v in grid.items() if policy.startswith("legacy:")]
        if len(controls) == 4:
            attempts = cur["attempts"]
            certain = [x for x in attempts if all(differs(x["path"], p) for p in controls)]
            counts["attempts_distinct_from_all_four"] += len(certain)
            counts["attempts_compared_to_four"] += len(attempts)
            counts["root_distinct_from_all_four"] += bool(certain)
            if any(x["status"] == "qualified_win" and not x["risks"] for x in certain):
                counts["distinct_winning_first_route"] += 1
                witnesses.setdefault("distinct_win", rid)
        if mode == "learned":
            control = grid["repair", cap]["attempts"]
            if control and cur["attempts"]:
                first = cur["attempts"][0]
                counts["first_spec_changed"] += first["strategy_hash"] != control[0]["strategy_hash"]
                changes.append(differs(first["path"], control[0]["path"]))
    return dict(counts=dict(counts), learned_first_action_sequence_changed=sum(changes),
                learned_first_pairs=len(changes), common_hp_delta=numbers(hp_delta), witnesses=witnesses)


def analyze(directory, target):
    target.mkdir(parents=True, exist_ok=False)
    report, grids, all_cases, examples = {}, {}, [], []
    all_hashes = {}
    with closing(store.open_store(directory/"search.sqlite")) as db:
        for phase in ("pilot", "development", "report"):
            rows = source_rows(db, phase)
            manifest = next(rows)
            pairs = list(rows)
            if len(pairs) != len(manifest["jobs"]):
                raise ValueError("Unsettled root reservations")
            data = [(c, i) for c, i in pairs if i["outcome"] == "complete"]
            all_cases.extend(c | {"exact": i.get("exact")} for c, i in pairs)
            splits = Counter(c["spec"]["character"] for c, _ in data)
            batches = [store.unpack(b[0]) for b in db.execute("SELECT data FROM batches WHERE plan=?", (phase,))]
            summary = dict(requests=len(pairs), complete=len(data), source=dict(Counter(c["source"] for c,_ in data)),
                roles=dict(splits), builds=len({c["recipe"] for c,_ in data}),
                encounters=len({c["spec"]["encounter"] for c,_ in data}),
                cards=len({v["card"]["spec_ref"] for _,i in data for v in i["public"]["identity_deck"]["cards"]}),
                acts=dict(Counter(c["spec"]["act"] for c,_ in data)),
                partial=sum(bool(i["gaps"]) for _,i in data), manifest_sha=digest(manifest),
                budget=sum(j["reserved"] for j in manifest["jobs"]), versions=manifest["versions"],
                attempts_status=dict(Counter(i["outcome"] for _,i in pairs)), batches=batches)
            bucket = {}
            for c, item in data:
                grid = {}
                for cell in item["cells"]:
                    mode, index, cap = cell["profile"]
                    row = cell["outcome"]
                    grid[("legacy:"+index if mode == "legacy_probe" else mode, cap)] = row
                    if mode != "legacy_probe":
                        bucket.setdefault((mode, cap), []).append(row)
                    for a in row["attempts"]:
                        if a["repair_depth"] and a["status"] == "qualified_win" and not a["risks"]:
                            parent = next(p for p in row["attempts"] if p["strategy_hash"] == a["parent_strategy"])
                            if not any(e["phase"] == phase for e in examples):
                                examples.append(dict(phase=phase, root=c["id"], profile=cell["profile"],
                                    parent=parent, repaired=a, locked=row["locked"], first_replays=row["first_replays"]))
                if phase == "report":
                    grids[c["id"]] = grid
            summary["arms"] = {f"{mode}-{cap}": arm_stats(values) for (mode, cap), values in sorted(bucket.items())}
            report[phase] = summary
            for name, stream in (("public", (learning_root(c,i,phase) for c,i in data)),
                                 ("audit", (dict(case=c, result=i) for c,i in pairs))):
                path = target/f"{phase}-{name}.jsonl.gz"
                all_hashes[path.name] = write_shard(path, stream)
            path = target/f"{phase}-public.jsonl.gz"
            summary["exported_attempts"] = sum(1 for _ in training_examples(path))
            (target/f"{phase}-manifest.audit.json.gz").write_bytes(store.pack(manifest))
    if len({c["id"] for c in all_cases}) != len(all_cases):
        raise ValueError("Reused sample")
    check_splits(all_cases)
    caps = sorted({cap for mode, cap in next(iter(grids.values())) if mode == "baseline"})
    report["paired"] = {f"{mode}-{cap}": compare(grids, cap, mode) for mode in ARMS[1:] for cap in caps}
    for mode in ARMS:
        report.setdefault("higher_budget_only", {})[mode] = sum(eligible(g[mode,caps[-1]]) and
            not eligible(g[mode,caps[0]]) for g in grids.values())
    report["model"] = digest(read(directory/"model.json"))
    report["shards"] = all_hashes
    immutable(target/"summary.json", report)
    immutable(target/"repair-witnesses.json", examples)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    summary = analyze(args.directory, args.destination)
    print(summary["paired"])
