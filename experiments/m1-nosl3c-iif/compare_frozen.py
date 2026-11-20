"""Replay frozen routes and preserve the first failed component."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
from types import FunctionType

from audit import certify, targets
from replay_frozen import replay
from nosl_experience import save_json


def entries(folder):
    with closing(sqlite3.connect((folder / "training.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for step, key, raw in db.execute("SELECT step,root,rows FROM roots ORDER BY step,root"):
            yield step, key, json.loads(gzip.decompress(raw))


def trace(output, versions, item):
    step, key, batch = item
    row = next(iter(batch["rows"]), None)
    if row is None:
        result = dict(status="no_archived_trajectory")
    else:
        check = FunctionType(replay.__code__, replay.__globals__ | {"certify": certify})
        try:
            result = check(output, versions, batch["spec"], row)
        except (targets.BANK.f1.i2.StopRun, ValueError, RuntimeError, KeyError, TypeError) as error:
            result = dict(status="diagnostic_failure", detail=str(error))
    return dict(update=step, position=key, baseline=batch["status"], spec=batch["spec"],
                archived_actions=0 if row is None else len(row["transitions"]), result=result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path,nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    targets.configure()
    versions = targets.worker_bind(output,args.solver.resolve())
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for ledger in args.ledgers:
            results = []
            for result in pool.map(lambda item: trace(output, versions, item), entries(ledger)):
                results.append(result)
                save_json(output/(ledger.name+".json"),results, compress=False)
