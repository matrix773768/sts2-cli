"""Probe previously failed roots without modifying their historical ledger."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih3"))
from certification import bind, completion


def probe(output, versions, case):
    key, spec = case
    started = time.monotonic()
    worker = None
    phase = "launch"
    try:
        with ExitStack() as stack:
            worker = completion.targets.open_worker(output, stack, versions)
            ready = time.monotonic()
            phase = "synthetic_start"
            root, timing = completion.targets.CAPTURE(worker, spec)
            initialized = time.monotonic()
            phase = "f1_audit"
            worker.request("f1_audit")
            phase = "i1_n2_reset"
            state = worker.request("i1_n2_reset", arm="A", cap=128,
                                   potions=False, rejected=[])["episode"]
            phase = "i1_n2_close"
            worker.request("i1_n2_close")
            phase = "close"
        return dict(root=key, runtime=worker.engine.runtime_version,
                    ready_seconds=ready - started, root_seconds=timing["initialize_ms"] / 1000,
                    predictor_seconds=time.monotonic() - initialized,
                    decision=root["public_root"]["decision"], prediction=state["status"],
                    exit=worker.engine.proc.returncode, logs=str(worker.engine.log_dir))
    except (ValueError, RuntimeError, OSError) as error:
        return dict(root=key, phase=phase, error=str(error),
                    exit=worker.engine.proc.returncode if worker else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    versions = bind(output, args.solver.resolve())
    cases = []
    with closing(sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for step, key, blob in db.execute("SELECT step,root,rows FROM roots ORDER BY step,root"):
            row = json.loads(gzip.decompress(blob))
            if row["status"] in ("audit_failure", "engine_failure"):
                cases.append((f"{step}:{key}", row["spec"]))
    for workers, subset in ((1, cases), (2, cases[:4]), (4, cases[:4])):
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda case: probe(output, versions, case), subset))
        (output / f"workers-{workers}.json").write_text(
            json.dumps(dict(versions=versions, results=results), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
