"""Strictly check fixed predicted winning actions in independent native sessions."""
import argparse
import json
from pathlib import Path

from benchmark_n1 import ROOT, bank, diagnose, f3a, s3a, SPECIAL
from summarize import read

f3b = diagnose["f3b"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = read(args.result)
    args.output.mkdir(parents=True)
    versions = s3a.solver_binding(args.output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    audits = []
    for cohort in ("S2B-early", "S3B", "F3A"):
        wins = [r for r in rows if r["cohort"] == cohort and r["result"]["status"] == "predicted_win"]
        if not wins:
            continue
        row = next((r for r in wins if r["case"]["id"] == SPECIAL), wins[0])
        result = row["result"]
        history = result["history"][1:]
        fixed = dict(actions=[f3b.action_for_wire(node["action"]) for node in history],
                     stamps=[node["frame"]["stamp"] for node in history])
        if cohort == "F3A":
            s3a.HOST = "m1-n1-real-build"
            s3a.solver_binding(args.output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
            source = ROOT / "logs/m1-f3a-formal"

            def restored(_, root):
                return f3a.restored(source, root)

            check = f3b.expect_native(args.output, row["case"], fixed, restore=restored)
        else:
            check = diagnose["audit"](args.output, row["case"], versions, dict(
                method=result["strategy"], root_sha256=row["root_sha256"], winner=fixed))
        audits.append(dict(cohort=cohort, id=row["case"]["id"], strategy=result["strategy"], check=check))
        bank.atomic(args.output / "audit.json", audits)


if __name__ == "__main__":
    main()

