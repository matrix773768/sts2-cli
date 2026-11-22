"""Resample each primary E3 witness once with its original archived behavior."""
from pathlib import Path
import sys

from verify_routes import PRIMARY

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-nosl3c-iij2"))
from resample import main

if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    for suite, step, root, _ in PRIMARY:
        main(output / suite, solver, suite=suite, cases=((step, root),),
             ledger_name=f"iij5b-serial-{suite}")
