"""Identify which archived risk stops were also reported by the unchanged Solver."""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import iig, targets
from compare_frozen import entries
from direct_probe import plans
from direct_recovery import original_replay
from nosl_experience import save_json
from replay_archive import read_matrix


def verify(output, solver, ledgers):
    targets.configure()
    versions = iig.bind(output, solver)
    source = read_matrix()
    cases = []
    for ledger in ledgers:
        chosen = {(r["step"], r["position"]) for r in source[ledger.name]
                  if r["category"] == "solver_execution_risk"}
        for step, root, batch in entries(ledger):
            if (step, root) in chosen:
                route = plans(output, versions, batch["spec"], batch["rows"][0])
                cases.append(dict(ledger=ledger.name, step=step, root=root, spec=batch["spec"], route=route))
    frozen = targets.BANK.f1.i2.SOLVER
    original = versions | dict(solver="0.51.5", solver_sha256=sha256(frozen.read_bytes()).hexdigest())
    os.environ["I1_SOLVER"] = str(frozen)
    for case in cases:
        case["boundaries"] = original_replay(output, original, case["spec"], case["route"])
    save_json(output / "original-risk.json", dict(engine=original, results=cases))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path, nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verify(output, args.solver.resolve(), args.ledgers)
