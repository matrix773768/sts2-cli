"""Run the frozen D2 utility reranking experiment and retrospective policy scoring."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from dc_common import ROOT, arms, config, frozen, read, write_json
from dc_metrics import average, describe, ledger, paired
from dc_utility import labels, observed_utilities, run_utility
from loop_battle import Host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, default=ROOT/"logs/m1-sv4a-host")
    args = parser.parse_args()
    output, cfg = args.output.resolve(), config() | {"direct_stop_margin":0.0}
    folder = output/"utility"
    folder.mkdir(exist_ok=True)
    families = [f for f in read(output/"roots/families.json")
                if f["split"] == "benchmark" and f["spec"]["max_hp"] <= 100]
    # Fixed 64-family, four-world subset independent of observed results.
    selected = sorted(families, key=lambda f:f["id"])[:64]
    ids = {f["id"] for f in selected}
    manifest = read(output/"roots/benchmark.json")
    jobs = [job for job in manifest["jobs"] if job[3] in ids]
    frozen(folder/"manifest.json", manifest | {"purpose":"dc1_utility_direct_natural_hp",
                                                "jobs":jobs})
    host = Host(output, args.host.resolve(), cfg)
    model = arms()["D2"]
    for variant in ("U1","U3"):
        result = run_utility(variant, host, folder/"manifest.json", folder/variant, cfg, *model)
        print(variant, result["status"], result["wall_s"], flush=True)
    original = ledger(output/"evaluation/benchmark/D2")
    rows = {"U0":{j[0]:original[j[0]] for j in jobs},
            **{variant:ledger(folder/variant) for variant in ("U1","U3")}}
    report = {}
    ap = defaultdict(Counter)
    for arm, items in rows.items():
        draws = defaultdict(list)
        for row in items.values():
            if row["complete"]:
                values = observed_utilities(labels(row), cfg["utility"])
                for k,v in values.items():
                    draws[k].append(v)
        report[arm] = dict(combat=describe(items.values()), retrospective={k:average(v) for k,v in draws.items()})
        if arm != "U0":
            report[arm]["paired"] = paired(((rows["U0"][i],items[i]) for i in items), bootstrap=True)
            for i,r in items.items():
                base = rows["U0"][i]
                if r["first"] and base["first"]:
                    if r["first"][0] != base["first"][0]:
                        raise ValueError("Opening public information changed between utility arms")
                    ap[arm]["opening_action_changed"] += r["first"][1]["index"] != base["first"][1]["index"]
    write_json(folder/"summary.json", dict(arms=report, reranking=ap))


if __name__ == "__main__":
    main()
