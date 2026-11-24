"""Terminal accounting, paired estimates, and fixed-budget complexity measurements."""
from collections import Counter
from statistics import mean
from math import ceil

import numpy as np

from dc_common import config
from loop_battle import read_ledger

WIN = "predicted_win"


def average(values):
    values = [value for value in values if value is not None]
    return mean(values) if values else None


def quantiles(values, levels=(.5, .9, .95, .99)):
    values = sorted(values)
    return {f"p{p*100:g}": values[max(0, ceil(len(values) * p) - 1)] for p in levels} if values else {}


def terminal(row):
    if not row["complete"]:
        return None
    root, final = row["root"], row["terminal"]
    net = root["hp"] - final["hp"]
    loss = row.get("cumulative_loss")
    return dict(net=net, cumulative=loss, max_delta=final["max_hp"]-root["max_hp"],
                healing=row.get("cumulative_healing"), hp_credit=loss-net if loss is not None else None,
                potions_left=sum(p is not None for p in final.get("potions", [])), gold=final.get("gold"),
                turns=final["turn"])


def describe(rows):
    rows = list(rows)
    statuses = Counter(row["status"] for row in rows)
    ends = [(row, terminal(row)) for row in rows if row["complete"]]
    net = [end["net"] for _, end in ends]
    wins = [end for row, end in ends if row["status"] == WIN]
    n = len(rows)
    if not n:
        return dict(attempts=0)
    cfg = config()
    return dict(attempts=n, statuses=statuses, complete=len(ends), win_rate=statuses[WIN]/n,
        death_risk=statuses["death"]/n, unresolved_rate=(n-len(ends))/n,
        mean_net=average(net), mean_cumulative=average(end["cumulative"] for _, end in ends),
        net_given_win=average(end["net"] for end in wins),
        cumulative_given_win=average(end["cumulative"] for end in wins),
        net_quantiles=quantiles(net), win_net_quantiles=quantiles([end["net"] for end in wins]),
        cumulative_quantiles=quantiles([end["cumulative"] for _, end in ends if end["cumulative"] is not None]),
        win_at_or_below={str(k):sum(end["net"] <= k for end in wins)/n for k in (0,5,10,20)},
        zero_net_win=sum(end["net"] == 0 for end in wins)/n,
        zero_cumulative_win=sum(end["cumulative"] == 0 for end in wins)/n,
        severe_rate=sum(end["net"] >= cfg["serious_loss_fraction"]*row["root"]["hp"] for row,end in ends)/n,
        worst_5pct_net=average(sorted(net, reverse=True)[:ceil(.05*len(net))]),
        worst_net=max(net, default=None),
        max_hp_gain=sum(end["max_delta"] > 0 for _, end in ends),
        mean_max_delta=average(end["max_delta"] for _, end in ends),
        mean_healing=average(end["healing"] for _, end in ends),
        mean_hp_credit=average(end["hp_credit"] for _, end in ends),
        hp_credit_count=sum(end["hp_credit"] is not None for _, end in ends),
        mean_potions_left=average(end["potions_left"] for _, end in ends),
        terminal_gold=average(end["gold"] for _, end in ends),
        turns=quantiles([end["turns"] for _, end in ends]), actions=quantiles([r["length"] for r in rows]),
        long=sum(row["length"] >= 128 or (end and end["turns"] >= 30) or 0
                 for row, end in [(r, terminal(r)) for r in rows]))


def dynamics(item):
    steps, graphs = item["row"]["steps"], item["search"]
    first = next((g for g in graphs if g["position"] == 0), {})
    usable = [g for g in graphs if "nodes" in g]
    counts = item["counts"]
    return dict(opening_legal=len(steps[0]["observation"]["actions"]) if steps else None,
        opening_nodes=first.get("nodes"), opening_transitions=first.get("transitions"), opening_stop=first.get("stop"),
        legal_counts=Counter(len(s["observation"]["actions"]) for s in steps),
        visited=sum(g["nodes"] for g in usable), graphs=len(usable), transitions=counts.get("transitions", 0),
        truncated_graphs=sum(v for k,v in counts.items() if k.startswith("stop_") and k != "stop_exhausted"),
        max_plan=max((len(g.get("path", [])) for g in usable), default=0),
        random=counts.get("boundary_random", 0), boundaries=counts.get("boundaries", 0),
        unsupported_boundaries=counts.get("boundary_unsupported", 0),
        pending=sum(s["observation"]["decision"]["phase"] == "choice" for s in steps),
        multi_target=sum(len({(a["target_side"], a["target"]) for a in s["observation"]["actions"]
                              if a.get("target") is not None}) > 1 for s in steps),
        disagreement=sum(g.get("chosen",g["direct"]) != g["direct"] for g in usable),
        score_spread=average(max(g["by_first"].values())-min(g["by_first"].values())
                             for g in usable if len(g["by_first"]) > 1),
        wall_s=item["wall_s"])


def ledger(path):
    rows = {}
    for r in read_ledger(path):
        row = r["row"]
        row["dynamic"] = dynamics(r)
        first = row["steps"][0] if row["steps"] else None
        row["first"] = [first["observation"], first["action"]] if first else None
        del row["steps"]
        rows[r["ordinal"]] = row
    return rows


def paired(pairs, bootstrap=False):
    pairs = list(pairs)
    if not pairs:
        return {"paired": 0}
    changes, clusters, joint_by_family, both, complete = Counter(), {}, {}, [], []
    cfg = config()
    for base, new in pairs:
        if base["root"] != new["root"] or base["family"] != new["family"]:
            raise ValueError("Paired roots differ")
        a, b = base["status"], new["status"]
        changes[f"{a} -> {b}"] += 1
        left, right = terminal(base), terminal(new)
        win = int(b == WIN) - int(a == WIN)
        death = int(b == "death") - int(a == "death")
        net = right["net"]-left["net"] if left and right else None
        cumulative = (right["cumulative"]-left["cumulative"]
                      if left and right and None not in (right["cumulative"], left["cumulative"]) else None)
        if net is not None:
            complete.append((net, cumulative))
            if a == b == WIN:
                both.append((net, cumulative))
                joint_by_family.setdefault(base["family"], []).append((net, cumulative))
        low = int(b == WIN and right["net"] <= cfg["low_loss_hp"]) - int(a == WIN and left["net"] <= cfg["low_loss_hp"])
        clusters.setdefault(base["family"], []).append([win, death, low])
    values = np.array([np.mean(items, axis=0) for items in clusters.values()])
    result = dict(paired=len(pairs), families=len(clusters), joint_complete=len(complete), joint_wins=len(both),
        changes=changes, win_delta=float(values[:,0].mean()), death_delta=float(values[:,1].mean()),
        low_loss_win_delta=float(values[:,2].mean()), complete_net_delta=average(d[0] for d in complete),
        complete_cumulative_delta=average(d[1] for d in complete),
        joint_win_net_delta=average(d[0] for d in both), joint_win_cumulative_delta=average(d[1] for d in both))
    if bootstrap:
        rng = np.random.default_rng(cfg["seed"])
        index = rng.integers(len(values), size=(2000,len(values)))
        sample = values[index].mean(axis=1)
        result["family_bootstrap_ci95"] = dict(zip(("win_delta","death_delta","low_loss_win_delta"),
                                                  np.quantile(sample,[.025,.975],axis=0).T.tolist(),strict=True))
        for offset, name in enumerate(("joint_win_net", "joint_win_cumulative")):
            per_family = [[d[offset] for d in joint_by_family.get(family, ()) if d[offset] is not None]
                          for family in clusters]
            family_sums = np.array([(sum(items),len(items)) for items in per_family])
            totals = family_sums[index].sum(axis=1)
            available = totals[:,1] > 0
            result["family_bootstrap_ci95"][name] = (
                np.quantile(totals[available,0]/totals[available,1],[.025,.975]).tolist()
                if available.any() else None)
    return result
