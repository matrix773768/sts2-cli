"""Resample the archived Glass Orb root using its original policy and seed."""
from pathlib import Path
import sys

from verify_route import LEDGER, ROOT, STEP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-nosl3c-iij2"))
from resample import main

if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    main(output, solver, suite="holdout", cases=((STEP, ROOT),), ledger_name=LEDGER)
