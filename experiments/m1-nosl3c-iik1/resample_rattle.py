"""Resample just the archived Rattle root with its original behavior."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-nosl3c-iij2"))
from resample import main

if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]), suite="pair16",
         cases=((0, "000009"),), ledger_name="iij5b-serial-pair16")
