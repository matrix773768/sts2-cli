"""Run the frozen native privacy and target probes against the IIG host."""
import argparse
from pathlib import Path
import sys
from types import FunctionType
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import bind, targets
from nosl_experience import save_json
from probe_equivalence import probe
from probe_targets import run
from training import Policy


def verify(output, solver):
    targets.configure()
    original = probe.__wrapped__
    privacy = FunctionType(original.__code__, original.__globals__ | dict(
        bind=bind, Policy=Policy, Decision=targets.Decision, project=targets.project))
    with torch.no_grad():
        save_json(output / "equivalence.json", privacy(output, solver))
    check_targets = FunctionType(run.__code__, run.__globals__ | dict(worker_bind=bind))
    check_targets(output, solver)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verify(output, args.solver.resolve())
