"""Compare end-to-end cold and resident costs for one identical on-policy update."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import perf_counter

from protocol import HERE, digest, read
from nosl3b_store import unpack
from nosl_experience import save_json


def measure(output, config, name, resident, workers):
    path = output / f"{name}.json"
    params = config | dict(domain="STS2-NOSL3C-BENCH-COMPLETE", resident=resident, workers=workers)
    save_json(path, params)
    run = output / name
    tick = perf_counter()
    with (output / f"{name}.log").open("wb") as log:
        subprocess.run([sys.executable, str(HERE / "run.py"), str(run), "--config", str(path),
                        "--through-update", "1"], stdout=log, stderr=subprocess.STDOUT, check=True)
    process_seconds = perf_counter() - tick
    with closing(sqlite3.connect(run / "training.sqlite")) as db:
        stats = unpack(db.execute("SELECT stats FROM snapshots WHERE step=1").fetchone()[0])
        rows = [r for raw, in db.execute("SELECT rows FROM roots WHERE phase='train' ORDER BY root")
                for r in unpack(raw)["rows"]]
    checkpoint = json.loads((run / "checkpoint-timings/u000001.json").read_bytes())["seconds"]
    seconds = stats["collect_seconds"] + stats["optimizer"]["seconds"] + checkpoint
    sem = digest([{k: row[k] for k in ("root", "mode", "behavior", "transitions", "feedback")} for row in rows])
    return dict(workers=workers, process_seconds=process_seconds, full_update_seconds=seconds,
                attempts_per_update_second=len(rows) / seconds, collect_seconds=stats["collect_seconds"],
                audit_ledger_write_seconds=stats["audit_ledger_write_seconds"],
                optimizer_seconds=stats["optimizer"]["seconds"], checkpoint_seconds=checkpoint,
                model_sha256=stats["optimizer"]["model_sha256"], semantic_sha256=sem,
                attempted=len(rows), qualified=stats["metric"]["eligible"], performance=stats["performance"])


def main(output, cfg):
    output.mkdir(parents=True, exist_ok=False)
    cold = measure(output, cfg, "cold", False, 1)
    resident = measure(output, cfg, "resident", True, 4)
    for field in ("model_sha256", "semantic_sha256", "attempted", "qualified"):
        if cold[field] != resident[field]:
            raise ValueError(f"End-to-end configuration differs at {field}")
    save_json(output / "complete-update.json", dict(identical_update=True, cold=cold, resident=resident))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "pilot.json")
    args = p.parse_args()
    main(args.output.resolve(), read(args.config))