"""Audit a completed INF1 STS2 smoke run and print compact reproducible evidence."""

import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
import sqlite3

from .common import ROOT, checksum, home_path, read, verify_assets
from .windows import process_identity


def audit_ledger(stage, target):
    from hashlib import sha256

    ledger = stage / "battle/results.sqlite"
    roots = read(stage / "roots.json")
    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        records = db.execute("SELECT ordinal,sha,payload FROM results ORDER BY ordinal").fetchall()
        sessions, seconds = db.execute("SELECT count(*),sum(seconds) FROM sessions").fetchone()
        contract = db.execute("SELECT json FROM contract").fetchone()[0]
    assert json.loads(contract)["manifest"] == checksum(stage / "roots.json")
    assert len(records) == len(roots["jobs"]) == target
    assert len({job[1]["seed"] for job in roots["jobs"]}) == target
    counts, identities = Counter(), set()
    for (index, expected, payload), (ordinal, spec, split, family, room) in zip(records, roots["jobs"], strict=True):
        raw = gzip.decompress(payload)
        assert sha256(raw).hexdigest() == expected
        item = json.loads(raw)
        row = item["row"]
        assert index == ordinal == item["ordinal"]
        assert row["family"] == family and row["room"] == room and row["split"] == split
        assert row["root"] == {key: value for key, value in spec.items() if key != "seed"}
        assert row["complete"] and row["terminal"] and row["status"] in ("death", "predicted_win")
        counts[row["status"]] += 1
        identities.add(row["id"])
    assert len(identities) == target
    return dict(attempts=target, unique_records=len(identities), sessions=sessions,
                seconds=round(seconds, 3), terminals=counts, ledger_sha256=checksum(ledger),
                roots_sha256=checksum(stage / "roots.json"))


def audit(home):
    import torch

    output = home / "jobs/sts2-smoke"
    report = read(output / "report.json")
    events = read(home / "smoke-observed.json")
    spec = report["spec"]
    verify_assets(spec)
    assert report["state"] == "completed" and report["errors"] == report["retries"] == 0
    assert all(run["cwd"] == spec["cwd"] for run in report["runs"])
    for run in report["runs"]:
        for owner in (run["owner"]["process"], run["owner"]["gate"], run["child"]):
            assert owner and process_identity(owner["pid"]) != owner
    completed = [run["stage"] for run in report["runs"] if run["outcome"]["state"] == "completed"]
    assert completed == ["experience", "features", "training", "development"]
    experience = audit_ledger(output / "experience", spec["limits"]["experience_roots"])
    development = audit_ledger(output / "development", spec["limits"]["development_roots"])
    assert read(output / "development/roots.json")["purpose"] == "development"
    feature = read(output / "features/manifest.json")
    for split in feature["shards"].values():
        for shard in split:
            assert checksum(output / "features" / shard["name"]) == shard["sha256"]
    train = output / "training"
    parent = ROOT / "logs/m1-sv4a-formal/models/D2/best-train.pt"
    snapshots = [torch.load(path, map_location="cpu", weights_only=True) for path in
                 (parent, train / "resume.pt", train / "best.pt", train / "best-train.pt")]
    older, latest, best, best_train = snapshots
    assert latest["updates"] == spec["limits"]["optimizer_updates"]
    assert [item["epoch"] for item in latest["curve"]] == list(range(latest["epoch"] + 1))
    assert latest["scheduler"]["last_epoch"] == latest["epoch"]
    assert best["epoch"] == best_train["epoch"] and best["identity"] == best_train["identity"]
    assert all(torch.equal(tensor, best_train["model"][key]) for key, tensor in best["model"].items())
    assert older["optimizer"]["state"].keys() == latest["optimizer"]["state"].keys()
    deltas = Counter(int(latest["optimizer"]["state"][key]["step"].item() - state["step"].item())
                     for key, state in older["optimizer"]["state"].items())
    assert set(deltas) == {latest["updates"]}, deltas
    pause = {item["event"]: item["progress"]["done"] for item in events if item["event"] in
             ("experience paused", "GPU training paused")}
    assert 0 < pause["experience paused"] < experience["attempts"]
    assert 0 < pause["GPU training paused"] < latest["epoch"]
    owner = read(home / "manager.json")
    assert not owner or process_identity(owner["pid"]) != owner
    with closing(sqlite3.connect((home / "queue.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE id='sts2-smoke'").fetchone()[0] == 1
        active = db.execute("SELECT count(*) FROM jobs WHERE state IN ('running','pausing')").fetchone()[0]
        assert active == 0
    return dict(baseline=spec["baseline"], task_sha256=spec["sha256"], environment=str(torch.__version__),
                report_sha256=checksum(output / "report.json"), observations_sha256=checksum(home / "smoke-observed.json"),
                active=active, pause=pause, experience=experience, development=development, features=feature["sizes"],
                training=dict(epochs=latest["epoch"], updates=latest["updates"], optimizer_step_deltas=deltas,
                              best_epoch=best["epoch"], peak_cuda_bytes=read(train / "summary.json")["peak_cuda_bytes"],
                              **{name: checksum(train / f"{name}.pt") for name in ("resume", "best", "best-train")}),
                seconds=round(report["seconds"], 3))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=".")
    args = parser.parse_args()
    print(json.dumps(audit(home_path(args.home)), indent=2))
