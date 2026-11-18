"""Check native differential evidence emitted by verify.py."""
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("STS2_F3DA_RESULTS", HERE.parents[1] / "logs/m1-f3d-a/formal"))


@pytest.fixture(scope="module")
def results():
    return json.loads((WORK / "results.json").read_bytes())


@pytest.mark.parametrize(("name", "baseline", "steps"), [
    ("shiv-lean", 9, 18), ("shiv-hive-stocked", 6, 26)])
def test_survivor_search_and_native_prefix(results, name, baseline, steps):
    case = results["cases"][name]
    assert results["cap"] == 128 and results["arm"] == "C" and not results["potions"]
    assert case["baseline"]["transitions"] == baseline
    assert case["baseline"]["node"]["frame"]["boundary"] == "PendingChoice"
    assert case["baseline"]["node"]["action"].get("choice") is None
    assert case["fixed_survivor_node"]["frame"]["boundary"] == "None"
    assert case["root"]["native"] == case["fixed_root"]["native"]
    prefix = case["prefix"]
    assert prefix["native_frame_sha256"] == prefix["predicted_frame_sha256"]
    assert prefix["pre_audit"]["rng"] == prefix["post_audit"]["rng"]
    assert prefix["choice"]["destination_verified"]
    replay = case["search"]["native_replay"]
    assert case["search"]["transitions"] == steps and case["search"]["status"] == "win"
    assert replay["strict_terminal"] and replay["matched_actions"] == steps
    assert all(s["actual_sha256"] == s["expected_sha256"] for s in replay["trace"])


def test_duplicate_exact_second_instance(results):
    duplicate = results["cases"]["shiv-lean"]["duplicate"]
    assert duplicate["native_frame_sha256"] == duplicate["predicted_frame_sha256"]
    assert duplicate["choice"]["destination_verified"]
    binding = duplicate["choice"]["binding"]
    assert binding["option"] == binding["source_index"] == duplicate["expected_index"]
    selected = binding["selected"]
    assert selected["card_id"] == "DEFEND_SILENT"
    assert selected["source_occurrence"] == selected["option_occurrence"] == 1
    assert binding["menu"].count(selected["state_key"]) == 2
    assert duplicate["pre_audit"]["rng"] == duplicate["post_audit"]["rng"]
