"""Repeat just the archived II-E Hammer Time policy attempt."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-nosl3c-iij2"))
from resample import main

if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]), suite="pair16",
         cases=((0, "000000"),), ledger_name="iii9a-sample-1")
