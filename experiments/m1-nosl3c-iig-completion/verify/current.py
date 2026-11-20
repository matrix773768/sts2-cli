"""Rerun the earlier selector, privacy and target probes on the completion build."""
import argparse
from pathlib import Path
import runpy
import sys
from types import FunctionType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import HERE, bind

IIG = HERE.parent / "m1-nosl3c-iig"


def verify(output, solver):
    for path, entry in (("probe_reveal.py", "probe"), ("verify/native.py", "verify")):
        original = runpy.run_path(str(IIG / path))[entry]
        FunctionType(original.__code__, original.__globals__ | {"bind": bind})(output, solver)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verify(output, args.solver.resolve())
