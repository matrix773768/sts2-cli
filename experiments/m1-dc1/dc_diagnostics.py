"""Review disclosed failures, then run fixed-world and independent NOSL diagnostics."""
import argparse
from collections import Counter
from pathlib import Path

from dc_common import PRIOR, ROOT, arms, config, frozen, read, write_json
from dc_metrics import WIN, describe, ledger, paired, terminal
from dc_roots import manifest, world
from loop_battle import Host, run


def historical(output):
    index = read(PRIOR/"roots/confirmation.json")
    source = PRIOR/"evaluation/confirmation"
    policies = {path.name: ledger(path) for path in sorted(source.iterdir()) if (path/"results.sqlite").exists()}
    failure = [i for i,row in policies["D2-search"].items() if row["status"] != WIN]
    if len(failure) != 44:
        raise ValueError("Unexpected published failure denominator")
    rows = []
    for i in failure:
        base = policies["D2-search"][i]
        wins = {arm:terminal(items[i]) for arm, items in policies.items() if items[i]["status"] == WIN}
        rows.append(dict(ordinal=i, family=base["family"], encounter=base["root"]["encounter"],
            hp=base["root"]["hp"], length=base["length"], terminal=terminal(base), rescue=wins,
            status=base["status"], baseline_outcomes={arm:items[i]["status"] for arm,items in policies.items()},
            baseline_actions={arm:items[i]["first"][1] if items[i]["first"] else None
                              for arm,items in policies.items()},
            classification="observed_win" if wins else "currently_unsolved"))
    frozen(output/"history-roots.json", index | dict(purpose="dc1_diagnostic_disclosed_sv4a", jobs=[
        index["jobs"][r["ordinal"]] for r in rows]))
    write_json(output/"history.json", dict(failures=len(rows), with_win=sum(bool(r["rescue"]) for r in rows),
        long=sum(r["length"]>=128 or r["terminal"]["turns"]>=30 for r in rows),
        by_hp=Counter(str(r["hp"]) for r in rows), rows=rows))


def candidates(output, root, cfg):
    direct, search = [ledger(root/"evaluation/development"/arm) for arm in ("D2","D2-search")]
    families = [r for r in read(root/"roots/families.json") if r["split"] == "development"]
    ranked = sorted(families, key=lambda f:(
        -sum(search[i]["status"] != WIN for i in f["worlds"]),
        -sum(direct[i]["status"] != search[i]["status"] for i in f["worlds"]),
        f["id"]))
    candidates = [f for f in ranked if f["spec"]["max_hp"] == 80][:cfg["combat_hp_shadow_families"]]
    if len(candidates) != cfg["combat_hp_shadow_families"]:
        raise ValueError("Insufficient natural HP development families")
    variants = {
        "normal": lambda s: s,
        "current-full": lambda s: s | {"hp": s["max_hp"]},
        "high-max-only": lambda s: s | {"max_hp": 999},
        "160": lambda s: s | {"hp": 160, "max_hp": 160},
        "999": lambda s: s | {"hp": 999, "max_hp": 999},
    }
    frozen(output/"selected.json", [f["id"] for f in candidates])
    for name, override in variants.items():
        jobs = [[i, override(world(f["spec"], cfg, f["id"], 0, "hp-diagnostic")), "diagnostic", f["id"], f["room"]]
                for i,f in enumerate(candidates)]
        frozen(output/f"hp-{name}.json", manifest(cfg, f"dc1_diagnostic_hp_{name}", jobs))
    jobs = [[i*12+world_i, world(f["spec"], cfg, f["id"], world_i, "repeat-diagnostic"),
             "diagnostic", f["id"], f["room"]] for i,f in enumerate(candidates[:16]) for world_i in range(12)]
    frozen(output/"repeats.json", manifest(cfg, "dc1_diagnostic_independent_repeats", jobs))

    early = [f for f in families if f["source"] in ("synthetic-normal","synthetic-synergy")
             and all(direct[i]["status"] == search[i]["status"] == WIN for i in f["worlds"])]
    easy = sorted(early, key=lambda f:f["id"])[:16]
    if not easy:
        raise ValueError("No natural HP development family qualifies for low-risk replication")
    jobs = [[i*24+world_i,world(f["spec"],cfg,f["id"],world_i,"low-risk-diagnostic"),
             "diagnostic",f["id"],f["room"]] for i,f in enumerate(easy) for world_i in range(24)]
    frozen(output/"low-risk.json",manifest(cfg,"dc1_diagnostic_low_risk_replication",jobs))


def resources(host, output, root):
    jobs = read(root/"roots/development.json")["jobs"]
    catalog = read(root/"roots/catalog.json")
    starter = catalog["characters"][0]["relics"]
    response = {}
    try:
        lane = host.lane()
        for name, extras in {"relic": {"relics":starter}, "potion":{"potions":catalog["potions"][:1]},
                             "both":{"relics":starter,"potions":catalog["potions"][:1]}}.items():
            lane.open()
            try:
                state = lane.request("pre0_start", spec=jobs[0][1] | extras, cap=256)["episode"]
                obs = host.project(state["observation"])
                response[name] = dict(relics=obs["relics"], potions=obs["potions"],
                                     allowed_potion_actions=sum(a["kind"]=="use_potion" for a in obs["actions"]))
            except (RuntimeError, KeyError, ValueError) as error:
                response[name] = {"result": str(error)}
            finally:
                lane.close()
    finally:
        host.close()
    write_json(output/"resources.json", response)


def summarize(output):
    history = read(output/"history.json")
    historical_search = ledger(output/"historical-1400")
    forced = ledger(output/"historical-force-end-turn")
    hp = {p.name:ledger(p) for p in sorted(output.glob("hp-*")) if p.is_dir()}
    normal = hp["hp-normal"]
    repeats = {arm:ledger(output/"repeats"/arm) for arm in ("D2","D2-search")}
    independent = {}
    for arm, rows in repeats.items():
        independent[arm] = {family:describe(r for r in rows.values() if r["family"] == family)
                            for family in sorted({r["family"] for r in rows.values()})}
    for row in history["rows"]:
        i = row["ordinal"]
        row["search_1400"] = historical_search[i]["status"]
        row["forced_end_turn"] = forced[i]["status"]
        row["valid_diagnostic_win"] = bool(row["rescue"]) or WIN in (row["search_1400"], row["forced_end_turn"])
    low = {arm:ledger(output/"low-risk"/arm) for arm in ("D2","D2-search")}
    if low["D2"].keys() != low["D2-search"].keys():
        raise ValueError("Missing paired low-risk worlds")
    write_json(output/"summary.json", dict(historical=history,
        found_historical=sum(row["valid_diagnostic_win"] for row in history["rows"]),
        hp={name:dict(full=describe(rows.values()), rescued=sum(normal[i]["status"] != WIN and r["status"] == WIN
                 for i,r in rows.items()), lost=sum(normal[i]["status"] == WIN and r["status"] != WIN
                 for i,r in rows.items())) for name,rows in hp.items()},
        independent=independent, low_risk={arm:describe(rows.values()) for arm,rows in low.items()},
        low_risk_paired=paired(((row,low["D2-search"][i]) for i,row in low["D2"].items()), bootstrap=True),
        resources=read(output/"resources.json")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, default=ROOT/"logs/m1-sv4a-host")
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--historical-only", action="store_true")
    args = parser.parse_args()
    root, cfg = args.output.resolve(), config() | {"direct_stop_margin":0.0}
    output = root/"diagnostics"
    output.mkdir(exist_ok=True)
    if args.review_only or not (output/"history.json").exists():
        historical(output)
    if args.review_only:
        return
    host = Host(root, args.host.resolve(), cfg)
    matrix = arms()
    weights, condition, _ = matrix["D2"]
    try:
        run(host, output/"history-roots.json", output/"historical-1400", cfg, weights, condition, 1400)
        run(host, output/"history-roots.json", output/"historical-force-end-turn", cfg,
            *matrix["D2-search"], forced="EndTurn")
        if args.historical_only:
            return
        candidates(output, root, cfg)
        for path in sorted(output.glob("hp-*.json")):
            run(host, path, output/path.stem, cfg, *matrix["D2-search"])
        for arm in ("D2","D2-search"):
            run(host, output/"repeats.json", output/"repeats"/arm, cfg, *matrix[arm])
            run(host, output/"low-risk.json", output/"low-risk"/arm, cfg, *matrix[arm])
        resources(host, output, root)
    finally:
        host.close()
    summarize(output)


if __name__ == "__main__":
    main()
