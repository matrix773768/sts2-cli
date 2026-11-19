"""Checks on the published benchmark ledger."""
from pathlib import Path

from summarize import read, summarize


HERE = Path(__file__).resolve().parent


def test_baseline_complete_and_disjoint():
    rows = read(HERE / "baseline.jsonl.gz")
    summary = summarize(rows)
    assert set(summary) == {"S2B-early", "S3B", "F3A"}
    for cohort, expected in (("S2B-early", 32), ("S3B", 96), ("F3A", 5)):
        assert set(summary[cohort]) == {"Q1", "AGGRO", "DEFENSIVE", "ENGINE"}
        assert all(group["all"]["all"]["n"] == expected for group in summary[cohort].values())
    for row in rows:
        assert row["evidence"] == "prediction_only"
        if row["synthetic"]:
            assert row["case"]["split"] == "development"
            assert row["natural_reachability"] == "unknown"


def test_one_trajectory_with_common_root():
    starts = {}
    for row in read(HERE / "baseline.jsonl.gz"):
        r = row["result"]
        if "history" not in r:
            assert r["status"] in {"unsupported", "root_prediction_mismatch"}
            continue
        key = row["cohort"], row["case"]["id"]
        assert r["start"]["stamp"] == starts.setdefault(key, r["start"]["stamp"])
        assert len(r["history"]) == r["action_count"] + 1
        assert r["action_count"] <= r["transitions"] <= 48
        assert r["transitions"] - r["action_count"] <= 1
        for idx, node in enumerate(r["history"]):
            assert node["id"] == idx
            assert node.get("parent") == (idx - 1 if idx else None)
            if idx:
                assert node["action"]["kind"] not in (1, "UsePotion")  # UsePotion


