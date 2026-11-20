"""Fork a stopped run after a proven idle-worker deadline fault in selection."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
from pathlib import Path
import runpy
import shutil
import sqlite3

from journal import Journal
from protocol import HERE, digest, read
from worker import Environment
from nosl_experience import save_json

ARCHIVE_PHASE = "selection_deadline_audit"


def fork(source, destination, old_config, new_config):
    if (source == destination or new_config.get("run_revision") == old_config.get("run_revision") or
            {k: v for k, v in new_config.items() if k != "run_revision"} !=
            {k: v for k, v in old_config.items() if k != "run_revision"}):
        raise ValueError("Recovery must use a new revision and identical experiment settings")
    if json.loads((source / "run-status.json").read_bytes())["state"] != "failed":
        raise ValueError("Source must have safely stopped with recorded failure")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "audit-only").mkdir()
    env = Environment(destination)
    make_identity = runpy.run_path(str(HERE / "run.py"))["run_identity"]
    identity = make_identity(new_config, env)
    with env.b1b.bank.writer(source), env.b1b.bank.writer(destination):
        with closing(sqlite3.connect(source / "training.sqlite")) as read_identity:
            parent_identity = json.loads(read_identity.execute("SELECT value FROM identity WHERE id=1").fetchone()[0])
        if parent_identity["config_sha256"] != digest(old_config) or parent_identity["engine"] != identity["engine"]:
            raise ValueError("Parent protocol or engine fingerprint does not match")
        with closing(Journal(source / "training.sqlite", parent_identity)) as parent:
            stage = parent.latest()
            if stage is None or stage >= old_config["updates"] or parent.done("report", stage):
                raise ValueError("A nonfinal checkpoint with unopened final roots is required")
            if parent.done("train", stage):
                raise ValueError("Recovery only applies before the next on-policy batch")
            rows = list(parent.rows("selection", stage))
            n = len(old_config["selection"]) * old_config["evaluation_reps"] * 2
            reasons = Counter(r["feedback"]["reason"] for r in rows)
            if len(rows) != n or not reasons["root_generation_failed"] or reasons["root_generation_failed"] / n <= old_config["max_fault_fraction"]:
                raise ValueError("No complete, faulted selection pass at the checkpoint")
            failed = {r["root"] for r in rows if r["feedback"]["reason"] == "root_generation_failed"}
            for identifier in failed:
                path = source / "audit-only" / f"selection-{stage}-{identifier}.json.gz"
                fault = json.loads(gzip.decompress(path.read_bytes())).get("fault", {})
                if fault.get("phase") != "root" or "Engine run deadline exceeded" not in fault.get("detail", ""):
                    raise ValueError("Selection failures were not exclusively idle-worker deadline faults")
            saved, _ = parent.load(stage)
            with closing(sqlite3.connect(destination / "training.sqlite")) as copy:
                parent.db.backup(copy)
                with copy:
                    for table in ("roots", "root_hashes"):
                        copy.execute(f"UPDATE {table} SET phase=? WHERE phase='selection' AND step=?",
                                     (ARCHIVE_PHASE, stage))
                    copy.execute("UPDATE identity SET value=? WHERE id=1",
                                 (json.dumps(identity, sort_keys=True, separators=(",", ":")),))
            with closing(Journal(destination / "training.sqlite", identity)) as checked:
                parent_seals = dict(parent.db.execute("SELECT step,sha FROM snapshots"))
                assert dict(checked.db.execute("SELECT step,sha FROM snapshots")) == parent_seals
                assert list(checked.rows(ARCHIVE_PHASE, stage)) == rows
            save_json(destination / "audit-only" / "original-selection.json.gz", rows, compress=True)
            recovery = dict(schema="sts2.nosl3c.deadline-recovery.v1", update=stage,
                            checkpoint_sha256=parent_seals[stage], model_sha256=saved["model_sha256"],
                            parent_protocol=parent_identity["config_sha256"],
                            revision=new_config["run_revision"], new_protocol=identity["config_sha256"],
                            preserved_checkpoint_seals=len(parent_seals),
                            inherited_training_roots=parent.db.execute(
                                "SELECT count(*) FROM roots WHERE phase='train'").fetchone()[0],
                            original_selection_attempts=n, original_faults=reasons["root_generation_failed"],
                            original_statuses=Counter(r["feedback"]["status"] for r in rows),
                            opened_final_before_fork=False)
    for name in ("reviews", "checkpoint-timings"):
        shutil.copytree(source / name, destination / name)
    save_json(destination / "recovery.json", recovery)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--old-config", type=Path, default=HERE / "formal-initial.json")
    p.add_argument("--new-config", type=Path, default=HERE / "formal.json")
    args = p.parse_args()
    fork(args.source.resolve(), args.destination.resolve(), read(args.old_config), read(args.new_config))