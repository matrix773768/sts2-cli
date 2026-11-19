"""Check the recorded real-engine evidence without rebuilding the game host."""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def test_snapshot_forks_isolate_mutable_state_but_retain_root_references():
    data = read("boundary.json")
    assert len(data["exports"]) == 2
    assert len({row["pid"] for row in data["exports"]}) == 2
    for case, row in zip(data["cases"], data["exports"], strict=True):
        assert case["live"] == row["continuation_sha256"]
        checks = row["observation"]
        for field in ("live_combat", "native_in_progress", "matches_projection", "live_unchanged",
                      "player_is_live_reference", "enemy_is_live_reference", "fork_rng_isolated",
                      "fork_player_state_isolated", "root_retains_private_simulator"):
            assert checks[field] is True, field
        assert checks["root_public_constructors"] == 0
        assert checks["root_export_error"]


def test_resident_import_roundtrips_stamps_without_a_predictive_root():
    data = read("boundary.json")
    a, b = data["exports"]
    attempts = data["imports"]
    assert [row["root_id"] for row in attempts] == [a["root_id"], b["root_id"], a["root_id"]]
    assert len({row["pid"] for row in attempts}) == 1
    assert attempts[0]["pid"] not in {a["pid"], b["pid"]}
    for source, attempt in zip((a, b, a), attempts, strict=True):
        assert attempt["continuation_sha256"] == source["continuation_sha256"]
        checks = attempt["observation"]
        assert checks["stamp_roundtrip"] is True
        assert checks["live_combat"] is False
        assert checks["native_in_progress"] is False
        assert "CombatSolver.CombatRootSnapshot" in checks["root_import_error"]


def test_frozen_load_comparison_retains_all_roots_and_routes():
    data = read("load.json")
    assert [b["workers"] for b in data["batches"]] == [1, 6, 2, 6]
    reference = data["batches"][0]["rows"]
    assert len(reference) == 6
    for batch in data["batches"]:
        for cold, repeated in zip(reference, batch["rows"], strict=True):
            assert repeated["root_id"] == cold["root_id"]
            assert repeated["prediction_difference"] == []
            assert repeated["route_and_frames_sha256"] == cold["route_and_frames_sha256"]
            assert repeated["transitions"] == cold["transitions"]
