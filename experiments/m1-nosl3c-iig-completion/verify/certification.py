"""Verify the unchanged semantic guard against a real completion-build death."""
import argparse
import json
from pathlib import Path
import runpy
import sys
from types import FunctionType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import ATTESTED_SOLVER, HERE
from nosl_experience import save_json

VALIDATE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iif/validate.py"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archived_json", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.archived_json.read_bytes())
    record = next(row["result"] for row in rows if row.get("result", {}).get("equivalence_proof"))
    qualifies = VALIDATE["qualifies"]
    test_terminal = VALIDATE["test_terminal"]
    pinned = FunctionType(qualifies.__code__, qualifies.__globals__ | {"SOLVER": ATTESTED_SOLVER})
    verify = FunctionType(test_terminal.__code__, test_terminal.__globals__ | {"qualifies": pinned})
    VALIDATE["test_menu"]()
    rejected = verify(record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_json(args.output, dict(rejected=rejected, positive=record["route"], rule=record["rule"]))
