"""Compare the same archived actions under the isolated completion Solver."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import gzip
import json
from pathlib import Path
from types import FunctionType

HERE = Path(__file__).resolve().parent
IIG = HERE.parent / "m1-nosl3c-iig"
from completion_engine import bind, certify, iig, targets
from compare_frozen import entries
from nosl_experience import save_json
from trace_archive import case, replay_with_trace


def read_matrix():
    return json.loads(gzip.decompress((IIG / "coverage.json.gz").read_bytes()))["rows"]


def final_classification(row):
    proof = row.get("result", {})
    if proof.get("terminal_verified"):
        return "certified_death" if proof["status"] == "admissible_death" else "certified_win"
    if proof.get("certification") == "semantic_native_match":
        return "certified_death"
    if row["category"] == "incomplete_archived_route" and not row["archived_actions"]:
        return "route_not_reconstructible"
    if row["category"] == "incomplete_archived_route":
        return "prefix_only"
    return row["category"]


def compare(output, versions, item, old):
    key = item[:2]
    before = old[key]
    trace = FunctionType(replay_with_trace.__code__, replay_with_trace.__globals__ |
                         {"certify": partial(certify, mode="semantic")})
    original = FunctionType(case.__code__, case.__globals__ | {"replay_with_trace": trace})
    after = original(output, versions, item, {key: before["previous"]})
    return after | {
        "before_iig": {name: before.get(name) for name in (
            "category", "latest_boundary", "consumed_decisions", "stable_boundary",
            "last_submitted", "trace", "terminal_verified")},
        "native_classification": final_classification(after),
        "new_trajectory": False,
    }


def run(output, solver, ledgers, workers, selected, frozen_host=False):
    targets.configure()
    versions = (iig.bind if frozen_host else bind)(output, solver)
    report = dict(versions=versions, ledgers={})
    past = read_matrix()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ledger in ledgers:
            old = {(r["step"], r["position"]): r for r in past[ledger.name]}
            roots = [item for item in entries(ledger)
                     if not selected or (ledger.name, *item[:2]) in selected]
            if not roots:
                continue
            rows = list(pool.map(lambda item: compare(output, versions, item, old), roots))
            save_json(output / (ledger.name + ".json"), rows)
            report["ledgers"][ledger.name] = dict(
                attempts=len(rows), statuses=Counter(row["native_classification"] for row in rows))
    save_json(output / "summary.json", report)


def selection(values):
    result = set()
    for value in values:
        ledger, batch, index = value.split(":")
        result.add((ledger, int(batch), f"{int(index):06d}"))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path, nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--frozen-host", action="store_true")
    parser.add_argument("--case", action="append", default=[], metavar="LEDGER:BATCH:ROOT")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run(output, args.solver.resolve(), args.ledgers, args.workers, selection(args.case), args.frozen_host)
