"""Stratified family estimates and curriculum admission from paired live battles."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from dc_common import config, frozen, read, write_json
from dc_metrics import WIN, average, describe, ledger, paired, terminal
from dc_produce import allocation
from dc_utility import labels, observed_utilities


def joined(output, source, arms):
    planned = read(output/"roots"/f"{source}.json")["jobs"]
    rows = {arm:ledger(output/"evaluation"/source/arm) for arm in arms}
    jobs = {job[0]:job for job in planned}
    for arm, items in rows.items():
        if items.keys() != jobs.keys():
            raise ValueError(f"Incomplete paired cohort: {source}/{arm}")
        for i,row in items.items():
            _, private, split, family, room = jobs[i]
            if (row["root"] != {k:v for k,v in private.items() if k != "seed"}
                    or row["family"] != family or row["room"] != room or row["split"] != split):
                raise ValueError(f"Ledger and frozen recipe differ: {source}/{arm}/{i}")
    return rows


def dynamic(rows):
    graphs = sum(r["dynamic"]["graphs"] for r in rows)
    legal = Counter()
    for row in rows:
        legal.update(row["dynamic"]["legal_counts"])
    result = {key:average([r["dynamic"][key] for r in rows])
              for key in ("wall_s","opening_legal","opening_nodes","opening_transitions","max_plan",
                          "transitions","random","pending","multi_target","score_spread")}
    result.update(graphs=graphs, legal_histogram=legal,
        opening_stops=Counter(r["dynamic"]["opening_stop"] or "unavailable" for r in rows),
        unavailable_opening=sum(r["dynamic"]["opening_transitions"] is None for r in rows),
        random_boundary_fraction=(sum(r["dynamic"]["random"] for r in rows) /
                                  (sum(r["dynamic"]["boundaries"] for r in rows) or 1)),
        graph_cutoff_fraction=sum(r["dynamic"]["truncated_graphs"] for r in rows)/graphs if graphs else None,
        graph_disagreement_fraction=sum(r["dynamic"]["disagreement"] for r in rows)/graphs if graphs else None)
    return result


def family_metrics(family, rows, protocol):
    ids = family["worlds"]
    d, s = [[rows[k][i] for i in ids] for k in ("D2","D2-search")]
    # The last two realizations of an evaluation family are held out from
    # empirical policy choice and quadrant assignment.
    n = 2 if len(ids)>2 else len(ids)
    training = {"D2":d[:n], "D2-search":s[:n]}
    def key(rows):
        return (sum(r["status"] != WIN for r in rows),
                sum(terminal(r)["net"] for r in rows if r["status"] == WIN))
    selected = min(training, key=lambda arm:key(training[arm]))
    established = [terminal(r) for r in training["D2"] if r["complete"]]
    risk = sum(r["status"] == "death" for r in d[:n])/n
    loss = average(r["net"] for r in established)
    complexity = dynamic(s[:n])
    measure = complexity["opening_transitions"]
    quadrant = "unknown"
    if measure is not None and loss is not None and len(established)==n:
        quadrant = ("B" if measure >= protocol["opening_transitions"] else "A") if loss <= protocol["net_hp"] else (
                    "D" if measure >= protocol["opening_transitions"] else "C")
    all_rows = d[:n]+s[:n]
    ends = [(r,terminal(r)) for r in all_rows]
    full = all(row["complete"] for row in all_rows)
    wins = sum(r["status"] == WIN for r in all_rows)
    divergence = sum(a["status"] != b["status"] for a,b in zip(d[:n], s[:n], strict=True))
    direct_to_search = paired(zip(d[:n],s[:n],strict=True))
    if not full or any(r["length"] >= 128 or (t and t["turns"] >= 30) for r,t in ends):
        category = "long_or_incomplete"
    elif not wins:
        category = "currently_unsolved"
    elif all(r["status"] == WIN and t["net"] <= protocol["net_hp"] for r,t in ends):
        category = "observed_low_loss"
    elif sum(r["status"] == WIN for r in s[:n]) > sum(r["status"] == WIN for r in d[:n]) or (
            direct_to_search["death_delta"] <= 0 and direct_to_search["joint_win_net_delta"] is not None
            and direct_to_search["joint_win_net_delta"] <= -5):
        category = "search_improvable"
    elif divergence:
        category = "policy_disagreement"
    elif wins == len(all_rows) and all(t["net"] > protocol["net_hp"] for _,t in ends):
        category = "high_loss_survival"
    elif wins <= len(all_rows)/2:
        category = "frequent_death"
    else:
        category = "undetermined"
    return family | dict(quadrant=quadrant, diagnosis=category, selected=selected, risk=risk, net=loss,
                         dynamics=complexity, D2=describe(d), search=describe(s), paired=direct_to_search)


def static_summary(families):
    return dict(families=len(families), by_source=Counter(f["source"] for f in families),
        by_stratum=Counter(f"{f['spec']['act']}:{f['room']}:{f['source']}" for f in families),
        hp=Counter(f"{f['spec']['hp']}/{f['spec']['max_hp']}" for f in families),
        packages=Counter(f["package"] or "none" for f in families),
        interactions=Counter(k for f in families for k in f["static"]["interactions"]),
        average_size=average(f["static"]["size"] for f in families),
        average_basics=average(f["static"]["basics"] for f in families),
        upgrade_fraction=(sum(f["static"]["upgraded"] for f in families) /
                          sum(f["static"]["size"] for f in families)))


def group(families, rows, holdout=False, bootstrap=False):
    if not families:
        return {"families":0}
    world_ids = [i for f in families for i in (f["worlds"][2:] if holdout else f["worlds"])]
    d,s = [[rows[k][i] for i in world_ids] for k in ("D2","D2-search")]
    empirical = [rows[f["selected"]][i] for f in families for i in f["worlds"][2:]] if holdout else []
    utilities = {}
    for arm, items in {"D2":d, "D2-search":s}.items():
        per_world = [observed_utilities(labels(r), config()["utility"]) for r in items if r["complete"]]
        utilities[arm] = {key:average(u[key] for u in per_world) for key in ("U0","U1","U2","historical")}
    return dict(families=len(families), direct=describe(d), search=describe(s), observed_utility=utilities,
                paired=paired(zip(d,s,strict=True), bootstrap=holdout or bootstrap), dynamic=dynamic(s),
                independent_selected=describe(empirical))


def rank_witnesses(rows):
    """Different actions in a shared public opening with observed continuations."""
    changes = Counter()
    cfg = config()["utility"]
    for i, first in rows["D2"].items():
        second = rows["D2-search"][i]
        if not (first["first"] and second["first"] and first["complete"] and second["complete"]):
            continue
        if first["first"][0] != second["first"][0]:
            raise ValueError("Shared world opening differs")
        if first["first"][1]["index"] == second["first"][1]["index"]:
            continue
        va,vb = [labels(r) for r in (first,second)]
        if va["death"] or vb["death"]:
            continue
        group = f"{first['root']['max_hp']}"
        old = lambda v: 1 + .25*(v["old_class"]-1)/31
        u, v = (observed_utilities(r,cfg) for r in (va,vb))
        sign = lambda x: (x>0)-(x<0)
        exact, coarse = sign(u["U0"]-v["U0"]), sign(old(va)-old(vb))
        changes[f"{group}:pairs"] += 1
        changes[f"{group}:grid_turns_order_into_tie"] += exact!=0 and coarse==0
        for key in ("U1","U2"):
            if u[key] is not None and v[key] is not None:
                alternative = sign(u[key]-v[key])
                changes[f"{group}:{key}_changes_order_or_tie"] += alternative != exact
                changes[f"{group}:{key}_reverses_order"] += alternative * exact < 0
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--protocol-only", action="store_true")
    args = parser.parse_args()
    output, cfg = args.output.resolve(), config()
    families = read(output/"roots/families.json")
    dev = joined(output,"development",cfg["arms"])
    opening = [r["dynamic"]["opening_transitions"] for r in dev["D2-search"].values()
               if r["dynamic"]["opening_transitions"] is not None]
    protocol = dict(opening_transitions=median(opening), net_hp=cfg["low_loss_hp"],
                    measured_on="all development worlds", reference="D2",
                    classification_worlds="first two. All train families have two.",
                    reevaluation_worlds="last two of four", budget=cfg["search_budget"])
    frozen(output/"classification-protocol.json", protocol)
    if args.protocol_only:
        return
    report, all_items = {}, []
    for pool in cfg["pools"]:
        rows = dev if pool=="development" else joined(output,pool,cfg["arms"])
        items = [family_metrics(f,rows,protocol) for f in families if f["split"] == pool]
        all_items.extend(items)
        sources = defaultdict(list)
        quadrants = defaultdict(list)
        by_hp = defaultdict(list)
        for f in items:
            sources[f["source"]].append(f)
            quadrants[f["quadrant"]].append(f)
            by_hp[str(f["spec"]["max_hp"])].append(f)
        report[pool] = dict(catalog=static_summary(items), overall=group(items,rows,bootstrap=True),
            natural=group(by_hp["80"],rows), diagnostics=Counter(f["diagnosis"] for f in items),
            by_risk=Counter(str(f["risk"]) for f in items), by_quadrant=Counter(f["quadrant"] for f in items),
            by_source={name:group(subset,rows) for name,subset in sources.items()},
            by_max_hp={name:group(subset,rows) for name,subset in by_hp.items()},
            opening_rank=rank_witnesses(rows), independently_selected=Counter(f["selected"] for f in items),
            heldout=group(items,rows,holdout=True) if pool != "train" else None,
            heldout_natural_early_survivors=group([f for f in by_hp["80"] if f["risk"] == 0 and
                f["diagnosis"] in ("observed_low_loss", "search_improvable", "high_loss_survival", "undetermined")],
                rows, holdout=True) if pool != "train" else None,
            heldout_quadrants={name:group(subset,rows,holdout=True) for name,subset in quadrants.items()}
                              if pool != "train" else None)
        controls = ("D0","S0","S2")
        if all((output/"evaluation"/f"{pool}-controls"/a/"summary.json").exists() for a in controls):
            control_rows=joined(output,f"{pool}-controls",controls)
            report[pool]["controls"] = {a:describe(items.values()) for a,items in control_rows.items()}
        print(pool, report[pool]["overall"]["direct"]["statuses"],
              report[pool]["overall"]["search"]["statuses"], flush=True)
    write_json(output/"family-analysis.json", all_items)
    admissions = defaultdict(list)
    for family in all_items:
        if family["split"] == "train":
            name, weight = allocation(family)
            admissions[name].append({"id":family["id"],"weight":weight,"source":family["source"],
                                     "quadrant":family["quadrant"],"diagnosis":family["diagnosis"]})
    write_json(output/"curriculum.json",admissions)
    write_json(output/"results.json", dict(protocol=protocol, pools=report))


if __name__ == "__main__":
    main()
