"""Replay two predetermined development controls on the original frozen host."""
import argparse
from functools import partial
from pathlib import Path

from run_probe import (
    bank, s2c, synth, f3a, f3b, quality, f5a, session, first_win, refine, CAP,
)

CONTROL = ("12a8a749", "660d09b2")


def strip(result):
    return {k: v for k, v in result.items() if k not in {"rpc_ms", "prepare_ms"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    measured = bank.read(args.development)["rows"]
    selection = bank.read(s2c.SELECTION)
    selection["selection"] = [r for r in selection["selection"] if r["split"] == "development"
                              and r["id"].startswith(CONTROL)]
    selection["pilot"] = []
    plan, roots = s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "all")
    versions = bank.versions_for_host(args.output, quality.HOST) | {
        "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
    f3a.equal("frozen native control host", plan["versions"], versions)
    rows = []
    for case, item in roots.items():
        row = next(r for r in measured if r["case"]["id"] == case and r["stress_hp"] is None)
        root = item["root"]
        restore = partial(synth.rebuild, session=session)
        if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
            restore = partial(quality.native_neutralize, restore=restore)
        with restore(args.output, root) as (game, _):
            first = first_win(game, False)
            fixed = refine(game, first, False)
        baseline = [f5a.compare(strip(original), strip(staged)) for original, staged in (
            (first, row["first"]["fixed"]), (fixed, row["refine"]["fixed"]))]
        f3a.equal("staged and original frozen modes", [[], []], baseline)
        adaptive = row["first"]["adaptive"]
        adaptive_quality = row["refine"]["adaptive"]
        selected = row["pareto"]["adaptive"][str(CAP)]
        candidates = [adaptive["winner"], *adaptive_quality.get("candidates", [])]
        routes = {route["key"]: route for route in [first["winner"],
                  next(c for c in candidates if c["key"] == selected["key"])]}
        checked = []
        for route in routes.values():
            evidence = f3b.expect_native(args.output, root, route, restore=restore, keep_frames=False)
            checked.append(dict(route=route["key"], predator_terminal=route["predator_terminal"],
                                evidence=evidence))
        rows.append(dict(case=case, baseline=baseline, native_controls=checked))
        bank.atomic(args.output / "audit.json", dict(versions=versions, rows=rows))


if __name__ == "__main__":
    main()
