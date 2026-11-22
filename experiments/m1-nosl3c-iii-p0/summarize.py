"""Read P0 counters and fixed-suite overlaps from local evidence without writing ledgers."""
from collections import Counter
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter


def read(path):
    return json.loads(path.read_bytes())


def roots(db_path):
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for payload, in db.execute("SELECT rows FROM roots WHERE phase='train'"):
            yield json.loads(gzip.decompress(payload))


def engine_counts(output):
    commands = Counter()
    exits = Counter()
    for directory in (output / "engine").glob("game-*"):
        with (directory / "commands.jsonl").open(encoding="utf-8") as log:
            commands.update(json.loads(line)["cmd"] for line in log)
        lifecycle = directory / "lifecycle.json"
        exits[str(read(lifecycle)["exit_code"]) if lifecycle.exists() else "missing"] += 1
    return dict(command_counts={cmd: commands[cmd] for cmd in (
        "i1_s3a_identity", "synthetic_start", "i1_begin", "i1_n2_step", "i1_iib_native_stamp")},
        exit_counts=exits)


def main(output):
    start = perf_counter()
    report = read(output / "summary.json")
    manifest, = read(output / "catalog/course-roots.json")
    combat_seeds = {item["spec"]["seed"] for item in manifest}
    assert len(combat_seeds) == len(manifest)
    overlap = {}
    for suite in ("pair16", "holdout"):
        ledger = Path(f"logs/iik5-{suite}/training.sqlite")
        if not ledger.is_file():
            overlap[suite] = None
            continue
        overlap[suite] = len(combat_seeds & {item["spec"]["seed"] for item in roots(ledger)})
        assert overlap[suite] == 0

    training = list(roots(output / "training/training.sqlite"))
    audit = [read(output / "training/audit" / f"000000-{item['root']}.json") for item in training]
    verification = report["verification"]
    print(json.dumps(dict(
        fixed_suite_seed_overlap=overlap,
        run_stats={phase: engine_counts(output / phase)
                   for phase in ("prediction", "certification", "training")},
        training_worker_s=sum(item["timing"]["total_ms"] for item in training) / 1000,
        training_audit_worker_s=sum(item["timing"].get("audit_ms", 0) for item in training) / 1000,
        training_retirement_worker_s=sum(item.get("retirement_ms", 0) for item in audit) / 1000,
        training_audit_statuses=Counter(item["status"] for item in audit),
        differences=verification["differences"],
        export_wall_s=perf_counter() - start,
    ), indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
