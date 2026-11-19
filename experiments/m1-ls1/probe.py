"""Run one declared root in baseline_search or learned_search, with optional model."""
import argparse
from pathlib import Path
from time import monotonic, perf_counter

from ls1_design import PROTOCOL, manifest
from loop import bank, cell, load_model, model, ms, restore, setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline_search", "learned_search"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", required=True)
    parser.add_argument("--budget", type=int, choices=PROTOCOL["budgets"], required=True)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    case = next((c for c in manifest() if c["id"] == args.root), None)
    if case is None:
        parser.error("Root must be declared in the LS1 manifest")
    args.output.mkdir(parents=True, exist_ok=False)
    versions = setup(args.output)
    bundle = None
    bad_model = False
    if args.mode == "learned_search" and args.model and args.model.is_file():
        try:
            bundle = load_model(args.model, strict=True)
        except (KeyError, ValueError, TypeError, OSError):
            bad_model = True
    with restore(args.output, case, versions, monotonic() + 50) as (game, public, identity):
        tick = perf_counter()
        visible = {k: identity["resources"][k] for k in ("potions", "relics")}
        state, gaps = model.public_input(public, visible)
        prep = ms(tick)
        row = cell(game, case, state, gaps, versions, bundle,
                   (args.mode, args.budget // 2, args.budget, None), prep)
    if bad_model and row["audit"]["fallback"] == "model_missing":
        row["audit"]["fallback"] = "model_error"
    bank.atomic(args.output / "experience.json", row)
    print(row["outcome"]["status"], row["audit"]["fallback"] or "", flush=True)


if __name__ == "__main__":
    main()
