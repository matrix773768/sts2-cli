"""Freeze weighted production on new worlds from DC1 training families only."""
import argparse
from collections import Counter, defaultdict
import random
from pathlib import Path

from dc_common import ROOT, arms, checksum, config, digest, frozen, read
from dc_roots import manifest, world
from loop_battle import Host, run


def allocation(family):
    if family["diagnosis"] in ("long_or_incomplete", "currently_unsolved"):
        return "diagnose", 0.0
    if family["diagnosis"] in ("search_improvable", "policy_disagreement"):
        return "demonstrated-opportunity", 4.
    if family["quadrant"] == "B" and family["risk"] == 0 and family["spec"]["max_hp"] == 80:
        return "complex-low-loss", 3.
    if (family["D2"]["win_rate"] == family["search"]["win_rate"] == 1
            and (family["D2"]["net_given_win"] or 0) > 5):
        return "resource-optimization", 2.
    return "foundation-retention", 1.


def get_jobs(root, cfg, round_number, count):
    data = read(root/"family-analysis.json")
    frozen_train = {f["id"]:f for f in read(root/"roots/families.json") if f["split"] == "train"}
    if {r["id"] for r in data if r["split"] == "train"} != frozen_train.keys():
        raise ValueError("Curriculum analysis is not aligned with the frozen train pool")
    records = {}
    ranked = []
    for row in data:
        if row["split"] != "train":
            continue
        family = row["id"]
        original = frozen_train[family]
        if any(row[k] != original[k] for k in ("spec", "deck_family", "room")):
            raise ValueError("Training family recipe differs from the frozen pool")
        priority, weight = allocation(row)
        if not weight:
            continue
        key = random.Random(digest([cfg["seed"],round_number,family])).random() ** (1/weight)
        ranked.append((key, family))
        records[family] = (row,priority)
    if not 0 < count <= len(ranked):
        raise ValueError(f"Choose 1 to {len(ranked)} eligible distinct train families")
    order = sorted(ranked, reverse=True)
    by_priority = defaultdict(list)
    for entry in order:
        by_priority[records[entry[1]][1]].append(entry)
    minimum = max(1, count//10) if count >= len(by_priority) else 0
    initial = {entry[1] for entries in by_priority.values() for entry in entries[:minimum]}
    selected = [entry for entry in order if entry[1] in initial]
    selected.extend([entry for entry in order if entry[1] not in initial][:count-len(selected)])
    jobs, interests = [], Counter()
    channel = f"experience_dc1_{round_number}"
    for ordinal, (_, family) in enumerate(selected):
        row,priority = records[family]
        spec = world(row["spec"],cfg,family,0,channel)
        split = "validation" if int(row["deck_family"][:8],16)%7 == 0 else "train"
        jobs.append([ordinal,spec,split,family,row["room"]])
        interests[priority] += 1
    return manifest(cfg,channel,jobs) | {"interests":interests,
                "family_analysis":checksum(root/"family-analysis.json"), "minimum_per_available_category":minimum}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--arm", choices=("D2","D2-search"), default="D2")
    parser.add_argument("--max-new", type=int)
    parser.add_argument("--host", type=Path, default=ROOT/"logs/m1-sv4a-host")
    args = parser.parse_args()
    root, cfg = args.output.resolve(), config() | {"direct_stop_margin":0.0}
    output = root/"production"/f"round-{args.round}"
    output.mkdir(parents=True,exist_ok=True)
    specification = get_jobs(root,cfg,args.round,args.count)
    path = output/"manifest.json"
    frozen(path,specification)
    host = Host(root,args.host.resolve(),cfg)
    run(host,path,output/args.arm,cfg,*arms()[args.arm],epsilon=.05,max_new=args.max_new)


if __name__ == "__main__":
    main()
