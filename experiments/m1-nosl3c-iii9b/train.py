"""Run the existing v4 suites under the pinned II-I cumulative build."""
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii9a"))
from replay import SOLVER, bind, certification

if __name__ == "__main__":
    certification.bind = bind
    certification.SOLVER = SOLVER
    runpy.run_path(str(certification.HERE / "train.py"), run_name="__main__")
