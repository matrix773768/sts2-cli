"""Paired attribution summaries for frozen historical and new development roots."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median

from repeat_study import BASE, BASELINE, n2b, read
# The N2B and N2C scripts intentionally share the same reporting functions.
from diagnose import pair
from analyze import summary


def models_on(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["model"]].append(row)
    return groups


def median_present(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return median(values) if values else None


def summarize(data, frozen, report):
    old = {i["case"]["id"]:i["case"] for i in read(BASE/"manifest.json")["cases"]}
    new = {i["case"]["id"]:i["case"] for i in report["cases"]}
    prior = read(BASELINE/"ledger.json.gz")
    passes = {p["phase"]:p for p in data["passes"]}
    model_ids = [m["id"] for m in frozen["models"]]
    stages = {
        "old_train_controls":passes["zero-train"]["rows"],
        "selection":passes["selection"]["rows"],
        "historical_report":prior["passes"][-1]["rows"]+passes["historical-report"]["rows"],
        "new_report":passes["report"]["rows"],
    }
    phases = {}
    for name, rows in stages.items():
        cases = new if name == "new_report" else old
        group = models_on(rows)
        metrics = {}
        for model, items in group.items():
            strata = {}
            dimensions = {"encounter":lambda c:c["spec"]["encounter"], "template":lambda c:c["template"],
                          "character":lambda c:c["spec"]["character"], "pressure":lambda c:c["complexity"]}
            if name == "new_report":
                dimensions["arm"] = lambda c:c["arm"]
            for dimension, selector in dimensions.items():
                subsets = defaultdict(list)
                for row in items:
                    subsets[selector(cases[row["id"]])].append(row)
                strata[dimension] = {k:summary(subset) for k,subset in subsets.items()}
            actions = [r["terminal"].get("actions",0) for r in items]
            metrics[model] = dict(overall=summary(items), strata=strata, longest=max(actions),
                                  over_48=sum(n>48 for n in actions),
                                  mean_score_us=1000*sum(r["decision_ms"] for r in items)/max(1,sum(actions)))
        pairs = {}
        if name in ("new_report","historical_report"):
            for i, left in enumerate(model_ids):
                for right in model_ids[i+1:]:
                    comparison = pair(group[left],group[right])
                    if name == "new_report":
                        for dim, key in (("arm",lambda c:c["arm"]),("encounter",lambda c:c["spec"]["encounter"])):
                            comparison[dim] = {
                                label:pair([r for r in group[left] if key(cases[r["id"]])==label],
                                           [r for r in group[right] if key(cases[r["id"]])==label])
                                for label in sorted({key(c) for c in cases.values()})}
                    pairs[f"{left}/{right}"] = comparison
        phases[name] = dict(metrics=metrics, paired=pairs)

    budget = Counter()
    timing = {}
    for run in data["passes"]:
        rows = run["rows"]
        terminals = [r["terminal"] for r in rows]
        stops = Counter(t["status"] for t in terminals)
        transitions = sum(t.get("transitions",0) for t in terminals)
        if run["phase"].startswith("generation"):
            names = {m["id"]:(m["repeat"],m["method"]) for m in run["models"]}
            budget.update("/".join(names[r["model"]]) for r in rows)
        histories = defaultdict(list)
        for row in rows:
            histories[row["id"]].append(row)
        first = [group[0] for group in histories.values()]
        hot = [r for group in histories.values() for r in group[1:]]
        timing[run["phase"]] = dict(
            wall_ms=run["wall_ms"], stops=dict(stops), n=len(rows),
            complete_per_second=1000*sum(stops[s] for s in n2b.NORMAL)/run["wall_ms"],
            episode_ms=sum(r["episode_ms"] for r in rows),
            strategy_ms=sum(r["decision_ms"] for r in rows),
            observe_ms_per_transition=sum(t.get("observe_ms",0) for t in terminals)/max(1,transitions),
            replay_ms_per_transition=sum(t.get("replay_ms",0) for t in terminals)/max(1,transitions),
            cold_episode_ms_p50=median_present(first, "episode_ms"),
            warm_episode_ms_p50=median_present(hot, "episode_ms"),
            cold_prepare_ms_p50=median_present(first, "prepare_ms"),
            warm_prepare_ms_p50=median_present(hot, "prepare_ms"),
            launch_ms=sum(x["launch_ms"] for x in run["lifecycle"]),
            initialize_ms=sum(x["build"]["initialize_ms"] for x in run["lifecycle"]),
            recycle_ms=sum(x["recycle_ms"] for x in run["lifecycle"]),
            peak_bytes=max((r.get("memory") or 0) for r in rows),
            resident_growth_p50=median(values[-1]["working_set"]-values[0]["working_set"] for values in histories.values()))
    individual_locks = {m["id"]:n2b.stamp(m) for m in frozen["models"]}
    return dict(phases=phases, budget=dict(budget), timing=timing, elapsed_ms=data["elapsed_ms"],
                individual_locks=individual_locks,
                optimizer_ms=sum(g["optimizer_ms"] for g in data["updates"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args = parser.parse_args()
    directory = args.directory
    print(json.dumps(summarize(read(directory/"ledger.json"),read(directory/"models.json"),
                               read(directory/"manifest.json")),indent=2))
