"""Verify the recorded build-root and retirement invariants."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_cold_and_resident_a_b_a_have_identical_predictions_and_native_controls():
    data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    assert data["input"] == json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    assert [b["resident"] for b in data["batches"]] == [False, True, False, True]
    references = {}
    for batch in data["batches"]:
        rows = batch["rows"]
        assert [row["case"] for row in rows] == ["A", "B", "A"]
        assert len({row["pid"] for row in rows}) == (1 if batch["resident"] else 3)
        for row in rows:
            key = row["case"]
            assert row["prediction_differences"] == []
            observed = [row[field] for field in (
                "root_sha256", "actions", "prediction_stamps", "transitions", "winner_key")]
            assert references.setdefault(key, observed) == observed
            if batch["resident"]:
                control, retired = data["cold_native_controls"][key], row["retirement"]
                assert retired["prediction_stamp_mismatch_steps"] == []
                assert retired["native_frames_sha256"] == control["native_frames_sha256"]
                assert (retired["hp"], retired["gold"], retired["potions"]) == (
                    control["hp"], control["gold"], control["potions"])
    assert references["A"][0] != references["B"][0]


def test_in_flight_combat_requires_legal_settlement_and_cancel_discards_process():
    data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    assert data["active_reset"]["rejected"]
    assert data["active_reset"]["exit_code"] != 0
    assert data["cancellation"]["discarded"]
    assert data["cancellation"]["exit_code"] != 0
