"""Summaries, paired report comparisons, and a common-cohort training diagnostic."""
import argparse
from collections import Counter, defaultdict
from statistics import median
import json
from pathlib import Path

from train import base, rank, NORMAL, HERE
from policy import GROWTH, DEFENSE
from analyze import read, summary


def by_model(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["model"]].append(row)
    return groups


def pair(left, right):
    result = Counter()
    hp_difference = []
    for a, b in zip(sorted(left, key=lambda r:r["id"]), sorted(right, key=lambda r:r["id"]), strict=True):
        assert a["id"] == b["id"]
        a, b = a["terminal"], b["terminal"]
        if a["status"] not in NORMAL or b["status"] not in NORMAL:
            result["missing"] += 1
        elif a["status"] != b["status"]:
            result["left_only_win" if a["status"] == "predicted_win" else "right_only_win"] += 1
        elif a["status"] == "death":
            result["both_dead"] += 1
        else:
            result["both_win"] += 1
            x, y = (v["feedback"]["combat_terminal"] for v in (a,b))
            hp_difference.append(x["hp"]/x["max_hp"]-y["hp"]/y["max_hp"])
    return dict(counts=dict(result), joint_win_normalized_hp_delta_median=median(hp_difference) if hp_difference else None)


def behavior(rows):
    counts = Counter()
    for row in rows:
        for step in row["trajectory"]:
            action = step["action"]
            counts[action["action"]] += 1
            if action["action"] == "end_turn":
                continue
            args = action["args"]
            card = step["observation"]["hand"][args["card_index"]]["id"]
            counts["growth"] += card in GROWTH
            counts["defense_card"] += card in DEFENSE or card.startswith("DEFEND")
            counts["explicit_discard"] += "choice_index" in action
            if "target_index" in args and len(step["observation"]["enemies"]) > 1:
                counts["multitarget_play"] += 1
                counts["multitarget_nonfirst"] += args["target_index"] != 0
    return dict(counts)


def summarize(ledger):
    cohort = HERE.parent / "m1-n2a2"
    cases = {i["case"]["id"]:i["case"] for i in read(cohort/"manifest.json")["cases"]}
    historical = [r for b in read(cohort/"benchmark.json.gz")["batches"] for r in b["rows"] if r["cap"]==96]
    runs = ledger["passes"]
    selection = runs[-2]["scores"]
    report = by_model(runs[-1]["rows"])
    generations = []
    for run, update in zip(runs[:4], ledger["updates"], strict=True):
        root_ids = {r["id"] for r in run["rows"]}
        trend = dict(phase=run["phase"], methods={},
                     archived_fixed={str(p):summary([r for r in historical if r["id"] in root_ids and r["defense_first"]==p])
                                     for p in (False,True)})
        for method, winner in update["champions"].items():
            model_ids = [m["id"] for m in run["models"] if m["method"] == method]
            stop_counts = Counter()
            for model in model_ids:
                stop_counts.update(run["scores"][model]["stops"])
            primary = sorted(model_ids, key=lambda k:rank(run["scores"][k]), reverse=True)
            only = sorted(model_ids, key=lambda k:rank(run["scores"][k])[:2], reverse=True)
            trend["methods"][method] = dict(id=winner, training=run["scores"][winner],
                                            selection=selection[winner], survival_champion=only[0],
                                            changed_ranks=sum(a!=b for a,b in zip(primary,only)), totals=dict(stop_counts))
        generations.append(trend)
    metrics = {}
    for run in runs:
        rows = run["rows"]
        n = len(rows)
        done = sum(r["terminal"]["status"] in NORMAL for r in rows)
        metrics[run["phase"]] = dict(n=n, complete=done, wall_ms=run["wall_ms"],
                                    complete_per_second=1000*done/run["wall_ms"],
                                    total_policy_ms=sum(r["decision_ms"] for r in rows),
                                    total_episode_ms=sum(r["episode_ms"] for r in rows),
                                    policy_us_per_action=1000*sum(r["decision_ms"] for r in rows)/
                                         max(1,sum(r["terminal"].get("transitions",0) for r in rows)),
                                    peak_worker_bytes=max(r["memory"] for r in rows),
                                    root_launch_ms=sum(x["launch_ms"] for x in run["lifecycle"]),
                                    root_init_ms=sum(x["build"]["initialize_ms"] for x in run["lifecycle"]),
                                    root_recycle_ms=sum(x["recycle_ms"] for x in run["lifecycle"]))
    output = {}
    for model, rows in report.items():
        strata = {}
        for dimension, key in {"build":lambda c:c["template"], "encounter":lambda c:c["spec"]["encounter"],
                               "character":lambda c:c["spec"]["character"]}.items():
            groups = defaultdict(list)
            for row in rows:
                groups[key(cases[row["id"]])].append(row)
            strata[dimension] = {k:summary(v) for k,v in groups.items()}
        buckets = Counter(min(4, max(1, (r["terminal"]["actions"]+23)//24)) for r in rows)
        output[model] = dict(overall=summary(rows), strata=strata, behavior=behavior(rows),
                             length_buckets={f"{24*(k-1)+1}-{24*k}":buckets[k] for k in range(1,5)},
                             longest=max(r["terminal"]["actions"] for r in rows))
    comparisons = {f"{a}/{b}": pair(report[a],report[b])
                   for i,a in enumerate(report) for b in list(report)[i+1:]}
    initial = ledger["protocol"]["initial_mean"]
    deviations = {m["id"]:{key: w-b for key,w,b in zip(ledger["features"],m["weights"],initial,strict=True)}
                  for m in runs[-1]["models"] if "weights" in m}
    return dict(generations=generations, performance=metrics, selection=selection,
                deviations=deviations, report=output, paired=comparisons, elapsed_ms=ledger["elapsed_ms"])


def figure(summary):
    colors = {"cem":"#1d5b79", "random":"#b54e2b"}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="680" height="280" viewBox="0 0 680 280">',
             '<rect width="680" height="280" fill="#fff"/>',
             '<g font-family="sans-serif" font-size="13" fill="#202b33">']
    for metric, title, offset, n in (("training","Training batch (different roots)",0,12),
                                     ("selection","Shared selection cohort",340,24)):
        parts.append(f'<text x="{offset+50}" y="28" font-weight="bold">{title}</text>')
        for fraction in (0,.25,.5,.75,1):
            y=224-164*fraction
            parts.extend((f'<line x1="{offset+47}" y1="{y}" x2="{offset+300}" y2="{y}" stroke="#e4e8ec"/>',
                          f'<text x="{offset+43}" y="{y+4}" text-anchor="end">{fraction:.0%}</text>'))
        for method,color in colors.items():
            points=[(offset+68+i*70,224-164*g["methods"][method][metric]["wins"]/n)
                    for i,g in enumerate(summary["generations"])]
            parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="2"/>')
            parts.extend(f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>' for x,y in points)
        parts.extend(f'<text x="{offset+68+i*70}" y="245" text-anchor="middle">G{i+1}</text>' for i in range(4))
    parts.append('<text x="235" y="270" fill="#1d5b79">CEM champion</text><text x="354" y="270" fill="#b54e2b">Random champion</text></g></svg>')
    return "\n".join(parts)+"\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = summarize(read(args.ledger))
    base.bank.atomic(args.output/"summary.json", out)
    (args.output/"quality.svg").write_text(figure(out), encoding="utf-8")
