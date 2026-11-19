"""Frozen paired-factor contrasts at the base-condition level."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median

from run_factorial import n2b, read
from analyze import summary
from diagnose import pair

CELL = ((0,0),(0,1),(1,0),(1,1))


def paired_changes(rows, links):
    counts = Counter()
    hp = []
    for a,b in links:
        before,after = (rows[x]["terminal"] for x in (a,b))
        if any(x["status"] not in n2b.NORMAL for x in (before,after)):
            counts["missing"] += 1
            continue
        w0,w1 = (x["status"]=="predicted_win" for x in (before,after))
        counts[("win" if w0 else "death")+"→"+("win" if w1 else "death")] += 1
        if w0 and w1:
            u,v = [x["feedback"]["combat_terminal"] for x in (before,after)]
            hp.append(v["hp"]/v["max_hp"]-u["hp"]/u["max_hp"])
    return dict(counts=dict(counts),hp_delta_p50=median(hp) if hp else None)


def factorial(rows, cases):
    condition = defaultdict(dict)
    for row in rows:
        c = cases[row["id"]]
        condition[c["source_id"]][c["seed_index"],c["deck_index"]] = row
    sets = list(condition.values())
    if any(set(s)!=set(CELL) for s in sets):
        raise ValueError("Invalid factorial coverage")
    contrasts = {
        "seed_D0":((0,0),(1,0)), "seed_D1":((0,1),(1,1)),
        "deck_S0":((0,0),(0,1)), "deck_S1":((1,0),(1,1)),
        "joint":((0,0),(1,1)),
    }
    interactions = Counter()
    for cells in sets:
        statuses = [cells[k]["terminal"]["status"] for k in CELL]
        if any(x not in n2b.NORMAL for x in statuses):
            interactions["missing"] += 1
            continue
        a,b,c,d = (int(x=="predicted_win") for x in statuses)
        interactions[str((d-c)-(b-a))] += 1
    return dict(cells={f"S{s}D{d}":summary([x[s,d] for x in sets]) for s,d in CELL},
                contrasts={name:combine_changes(sets,links) for name,links in contrasts.items()},
                interactions=dict(interactions))


def combine_changes(sets, links):
    rows = {(i,k):row for i,cells in enumerate(sets) for k,row in cells.items()}
    return paired_changes(rows,[((i,links[0]),(i,links[1])) for i in range(len(sets))])


def rng_pairs(state,cases):
    pairs = defaultdict(dict)
    for id_,audit in state["root_audits"].items():
        c = cases[id_]
        pairs[c["source_id"],c["seed_index"]][c["deck_index"]] = audit
    differences = Counter()
    for p in pairs.values():
        for scope in ("run_rng","player_rng"):
            a,b = (p[i]["rng"][scope] for i in (0,1))
            differences.update(f"{scope}.{name}" for name in a.keys()|b.keys() if a.get(name)!=b.get(name))
        differences["opening_hand_changed"] += p[0]["hand"] != p[1]["hand"]
    return dict(n=len(pairs),differences=dict(differences))


def summarize(state,manifest):
    cases = {c["case"]["id"]:c["case"] for c in manifest["cases"]}
    fields = {"split":lambda c:c["diagnostic_split"], "template":lambda c:c["template"],
              "pressure":lambda c:c["complexity"],"encounter":lambda c:c["spec"]["encounter"]}
    overall = {}
    for model in manifest["models"]:
        rows = [r for r in state["rows"] if r["model"] == model["id"]]
        dimensions = {}
        for dimension,key in fields.items():
            groups = defaultdict(list)
            for row in rows:
                groups[key(cases[row["id"]])].append(row)
            dimensions[dimension] = {k:factorial(v,cases) for k,v in groups.items()}
        overall[model["id"]] = dict(total=summary(rows),factorial=factorial(rows,cases),dimensions=dimensions,
            score_us=1000*sum(r["decision_ms"] for r in rows)/max(1,sum(r["terminal"].get("actions",0) for r in rows)))
    pairs = {}
    for other in manifest["models"][1:]:
        pairs[other["id"]] = {}
        for split in ("all","diagnosis","report"):
            rows=[r for r in state["rows"] if split=="all" or cases[r["id"]]["diagnostic_split"]==split]
            pairs[other["id"]][split] = pair([r for r in rows if r["model"]==other["id"]],
                                            [r for r in rows if r["model"]=="initial-mean"])
    n = len(state["rows"])
    complete = sum(r["terminal"]["status"] in n2b.NORMAL for r in state["rows"])
    lifecycle=state["lifecycle"]
    return dict(models=overall, versus_mean=pairs, rng=rng_pairs(state,cases),
                timing=dict(n=n,complete=complete,wall_ms=state["elapsed_ms"],
                            feedback_per_s=1000*complete/state["elapsed_ms"],
                            prepare_ms_p50=median(r["prepare_ms"] for r in state["rows"] if r["prepare_ms"] is not None),
                            cold_init_ms_p50=median(r["build"]["initialize_ms"] for r in lifecycle),
                            recycle_ms_p50=median(r["recycle_ms"] for r in lifecycle),
                            peak_bytes=max(r["memory"] for r in state["rows"])))


if __name__=="__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("output",type=Path)
    directory = args.parse_args().output
    print(json.dumps(summarize(read(directory/"ledger.json"),read(directory/"manifest.json")),indent=2))
