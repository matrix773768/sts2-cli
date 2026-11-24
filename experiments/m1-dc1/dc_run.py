"""Freeze and run the paired DC1 experiment using the published SV4A battle ledger."""
import argparse
from pathlib import Path

from dc_common import ROOT, arms, config, frozen
from dc_roots import freeze
from loop_battle import Host, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, default=ROOT / "logs/m1-sv4a-host")
    parser.add_argument("--stage", choices=("freeze", "smoke", "primary", "controls"), default="primary")
    parser.add_argument("--pool", choices=tuple(config()["pools"]))
    args = parser.parse_args()
    output, cfg = args.output.resolve(), config()
    output.mkdir(parents=True, exist_ok=True)
    host = Host(output, args.host.resolve(), cfg)
    roots = output / "roots"
    identity = freeze(host, roots, cfg)
    if args.stage == "freeze":
        return
    cfg = cfg | {"direct_stop_margin": 0.0}
    matrix = arms()
    if matrix["D2-search"][2] != cfg["search_budget"]:
        raise ValueError("Frozen D2-search budget differs from the DC1 protocol")
    frozen(output / "arms.json", {k: [p.relative_to(ROOT).as_posix(), condition, budget]
                                   for k, (p, condition, budget) in matrix.items()})
    if args.stage == "smoke":
        path = roots / "development-controls.json"
        for name in cfg["arms"]:
            destination = output / "smoke" / name
            first = run(host, path, destination, cfg, *matrix[name], attempts=32, max_new=8)
            final = run(host, path, destination, cfg, *matrix[name], attempts=32)
            if (first["attempts"] not in (8, 32) or final["attempts"] != 32 or
                    final["status"].get("error") or final["counts"].get("terminal_mismatch")):
                raise RuntimeError(f"DC1 smoke or resume failure: {destination}")
        return
    controls = args.stage == "controls"
    for pool in (args.pool,) if args.pool else identity["config"]["pools"]:
        name = f"{pool}-controls" if controls else pool
        for arm in ("D0", "S0", "S2") if controls else cfg["arms"]:
            result = run(host, roots / f"{name}.json", output / "evaluation" / name / arm, cfg, *matrix[arm])
            print(name, arm, result["status"], result["wall_s"], flush=True)


if __name__ == "__main__":
    main()
