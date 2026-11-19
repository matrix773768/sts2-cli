"""Summarize feedback density with paired roots as the counting unit."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from statistics import median

NORMAL = ("predicted_win", "death")


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def summary(rows):
    status = Counter(r["terminal"]["status"] for r in rows)
    wins = [r["terminal"]["feedback"]["combat_terminal"] for r in rows
            if r["terminal"]["status"] == "predicted_win"]
    complete = sum(status[k] for k in NORMAL)

    def med(values):
        values = list(values)
        return median(values) if values else None

    return dict(n=len(rows), stops=dict(status), complete=complete,
                coverage=complete/len(rows), unconditional_win=len(wins)/len(rows),
                conditional_win=len(wins)/complete if complete else None,
                hp_p50=med(r["hp"] for r in wins),
                normalized_hp_p50=med(r["hp"]/r["max_hp"] for r in wins),
                loss_p50=med(r["terminal"]["feedback"]["combat_terminal"]["cumulative_loss"] for r in rows
                             if r["terminal"]["status"] in NORMAL),
                actions_p50=med(r["terminal"]["actions"] for r in rows if "actions" in r["terminal"]),
                transitions_p50=med(r["terminal"]["transitions"] for r in rows if "transitions" in r["terminal"]))


def paired(rows):
    by_root = defaultdict(dict)
    for row in rows:
        if row["defense_first"] in by_root[row["id"]]:
            raise ValueError("Duplicate strategy on one root")
        by_root[row["id"]][row["defense_first"]] = row["terminal"]
    counts = Counter()
    for sides in by_root.values():
        if len(sides) != 2:
            raise ValueError("Expected exactly two strategies")
        a, b = sides[False], sides[True]
        if a["status"] not in NORMAL or b["status"] not in NORMAL:
            counts["incomparable"] += 1
        elif a["status"] != b["status"]:
            counts["win_disagreement"] += 1
            counts["attack_only_win" if a["status"] == "predicted_win" else "defense_only_win"] += 1
        elif a["status"] == "death":
            counts["both_dead"] += 1
        else:
            counts["both_win"] += 1
            ax, bx = (r["feedback"]["combat_terminal"] for r in (a, b))
            if ax["hp"] * bx["max_hp"] != bx["hp"] * ax["max_hp"]:
                counts["hp_disagreement"] += 1
    valid = len(by_root) - counts["incomparable"]
    return dict(roots=len(by_root), paired=valid, categories=dict(counts),
                survival_distinguishable=counts["win_disagreement"],
                hp_distinguishable=counts["win_disagreement"] + counts["hp_disagreement"],
                d_win=counts["win_disagreement"]/valid if valid else None)


def analyze(data, manifest):
    cases = {item["case"]["id"]: item["case"] for item in manifest["cases"]}
    rows = [r for batch in data["batches"] for r in batch["rows"]]
    dimensions = dict(cohort=lambda c: c["cohort"], build=lambda c: c["template"],
                      pressure=lambda c: c["complexity"], encounter=lambda c: c["spec"]["encounter"],
                      character=lambda c: c["spec"]["character"])
    reports = {}
    for cap in (48, 96):
        current = [r for r in rows if r["cap"] == cap]
        groups = {"all": {"all": current}}
        for name, key in dimensions.items():
            partition = defaultdict(list)
            for row in current:
                partition[key(cases[row["id"]])].append(row)
            groups[name] = partition
        reports[cap] = {dimension: {label: dict(paired=paired(group), pooled=summary(group),
                                                  attack=summary([r for r in group if not r["defense_first"]]),
                                                  defense=summary([r for r in group if r["defense_first"]]))
                                     for label, group in partition.items()}
                        for dimension, partition in groups.items()}
        reports[cap]["leave_one_encounter_out"] = {
            key: paired([r for r in current if cases[r["id"]]["spec"]["encounter"] != key])
            for key in groups["encounter"]}
    return reports


def timing(rows, wall_ms):
    total = sum(r["terminal"].get("transitions", 0) for r in rows)
    normal = sum(r["terminal"]["status"] in NORMAL for r in rows)
    counters = ("observe_ms", "replay_ms", "advance_ms")
    return dict(n=len(rows), complete=normal, wall_ms=wall_ms,
                attempts_per_second=1000*len(rows)/wall_ms,
                complete_per_second=1000*normal/wall_ms,
                transitions=total, transitions_per_second=1000*total/wall_ms,
                stops=dict(Counter(r["terminal"]["status"] for r in rows)),
                per_transition_ms={k: sum(r["terminal"].get(k, 0) for r in rows)/total
                                   for k in counters} if total else None,
                p50={k: median(samples) if (samples := [r[k] for r in rows if r.get(k) is not None]) else None
                     for k in ("episode_ms", "prepare_ms", "reset_ms", "decision_ms", "close_ms")},
                peak_bytes=max((r.get("memory") or 0 for r in rows), default=0))


def performance(data):
    batches = data["batches"]
    pool = batches[0]
    cold = [r for b in batches for r in b["rows"] if r["phase"] == "first"]
    primary = [r for b in batches for r in b["rows"]]
    init_ms = sum(r["ms"] for b in batches for r in b["roots"])
    live = [r for b in batches for r in b["lifecycle"]]
    cold_ms = init_ms + sum(r["episode_ms"] + r["close_ms"] for r in cold)
    cold_ms += sum(r["recycle_ms"] for r in live)
    rotation = batches[1:]
    return dict(
        cold=timing(cold, cold_ms),
        same=timing(pool["same"], pool["same_ms"]),
        resident_pool=timing(pool["repeats"], pool["repeats_ms"]),
        rotation=timing([r for b in rotation for r in b["rows"]], sum(b["wall_ms"] for b in rotation)),
        warm_primary=timing([r for r in primary if r["phase"] != "first"],
                            sum(b["primary_warm_ms"] for b in batches)),
        native_root_ms_total=init_ms,
        native_root_ms_p50=median(r["ms"] for b in batches for r in b["roots"]),
        process_launch_ms_p50=median(r["launch_ms"] for r in live),
        process_recycle_ms_p50=median(r["recycle_ms"] for r in live),
        pool_peak_sum_upper_bytes=sum(max(r["memory"] for r in pool["rows"] + pool["repeats"] + pool["same"]
                                           if r["id"] == root["id"] and r.get("memory"))
                                      for root in pool["roots"] if root["status"] == "native_built"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    data = read(args.results)
    print(json.dumps(dict(feedback=analyze(data, read(Path(__file__).with_name("manifest.json"))),
                          performance=performance(data)), indent=2))
