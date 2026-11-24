"""Run or resume the formal SV4A campaign."""
import argparse
import json
import os
from pathlib import Path

from loop_common import ROOT, ancestor, config, write_json
from loop_battle import Host, run
from loop_checks import run_checks
from loop_roots import freeze


def pretest(host, cfg, output, initial):
    target = output / "selection.json"
    if target.exists():
        return json.loads(target.read_bytes())
    run_checks(host, cfg, initial, output / "checks")
    model = ROOT / cfg["g0"]
    roots = output / "roots"
    for mode, budget in (("D0", 0), ("S0", cfg["budget_candidates"][0])):
        name = output / "smoke" / mode
        first = run(host, roots/"smoke.json", name, cfg, model, initial, budget, max_new=8)
        # On resume, the whole cohort still uses the original identity.
        final = run(host, roots/"smoke.json", name, cfg, model, initial, budget)
        if final["attempts"] != cfg["cohorts"]["smoke"] or final["status"].get("error",0):
            raise RuntimeError(f"The 32-root rehearsal failed: {mode}: {final}")
        if budget and (not final["counts"].get("replan_after_random")
                       or not final["counts"].get("executed_plan_steps")):
            raise RuntimeError("No live random-boundary replanning or plan execution in rehearsal")
    runs = []
    for budget in [0, *cfg["budget_candidates"]]:
        result = run(host, roots/"development.json", output/"pretest"/f"budget-{budget}", cfg,
                     model, initial, budget, attempts=cfg["pretest_roots"])
        if result["status"].get("error",0) or result["counts"].get("terminal_mismatch",0):
            raise RuntimeError(f"Pretest graph or execution failure under budget {budget}")
        runs.append(dict(budget=budget, wins=result["wins"], attempts=result["attempts"],
                         complete_per_s=result["complete_per_s"], counts=result["counts"]))
    candidates = [row for row in runs if row["budget"]]
    cutoff = max(row["wins"] for row in candidates) - 2
    selected = max((row for row in candidates if row["wins"] >= cutoff),
                   key=lambda row: (row["complete_per_s"], -row["budget"]))
    # Size production by measured end-to-end cost, including feature and RPC overhead.
    s_cap = min(cfg["experience_roots"]["S1"], max(768, int(selected["complete_per_s"] * 1500)))
    value = dict(budget=selected["budget"], search_attempts=s_cap, pretest=runs,
                 selection_rule="Fastest measured budget within two wins of best on 128 development roots",
                 production_rule="Reserve at least 768 roots, cap at 1500 measured search seconds per generation or the frozen maximum")
    write_json(target, value)
    print("frozen", value, flush=True)
    return value


def main():
    os.chdir(ROOT)
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    cli.add_argument("--host", type=Path, default=Path("logs/m1-sv4a-host"))
    cli.add_argument("--until", choices=("pretest","all"), default="all")
    cli.add_argument("--route", choices=("D","S","both"), default="both",
                     help="Run only the selected training route and its development evaluations")
    cli.add_argument("--device", default="cuda", choices=("cuda","cpu"))
    args = cli.parse_args()
    cfg = config()
    output = args.output.resolve()
    output.mkdir(exist_ok=True, parents=True)
    proof = ancestor(cfg)
    proof_path = output/"ancestor.json"
    if proof_path.exists():
        if json.loads(proof_path.read_bytes()) != proof:
            raise ValueError("Frozen G0 identity changed")
    else:
        write_json(proof_path, proof)
    initial = proof["policies"][1]
    host = Host(output, args.host.resolve(), cfg)
    freeze(host, output/"roots", cfg)
    selection = pretest(host, cfg, output, initial)
    if args.until == "pretest":
        return
    from stages import stages
    stages(host, output, cfg, selection, initial, args.device, args.route)


if __name__ == "__main__":
    main()
