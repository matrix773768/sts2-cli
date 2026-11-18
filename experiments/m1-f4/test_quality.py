"""Audit the reproducible F4 predictions and independent native evidence."""
import gzip
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path(os.environ.get("STS2_F4_RESULTS", ROOT / "logs/m1-f4/formal"))


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


FROZEN = read(HERE.parent / "m1-s2a/results.json")["f3b_selection"]


def assert_strict_win(native, count, hp):
    assert native["status"] == "win" and native["root_verified"] and native["strict_terminal"]
    assert native["matched_actions"] == count == len(native["trace"])
    assert all(step["expected_sha256"] == step["actual_sha256"] for step in native["trace"])
    assert native["trace"][-1]["terminal"]
    assert native["native_final"]["resources"]["hp"] == hp
    assert native["native_final"]["outcome"]["potions"] == []


@pytest.fixture(scope="module")
def report():
    result = read(OUT / "results.json")
    assert set(result["cases"]) == set(FROZEN)
    assert result["offline_oracle"] and result["potions"] is False
    return result


@pytest.mark.parametrize("name", FROZEN)
def test_budget_and_native_route_selection(report, name):
    row = report["cases"][name]
    control = row["baseline"]
    trials = read(OUT / name / control["history"])
    seed = trials[-1]
    base_hp = row["baseline_resources"]["hp"]
    assert_strict_win(seed["verification"], len(seed["actions"]), base_hp)
    baseline_cost = sum(trial["transitions"] + len(trial["actions"]) for trial in trials)
    assert row["baseline_total_charged"] == baseline_cost <= 128
    for label, result in row["tiers"].items():
        stage = OUT / name / label
        cap = int(label)
        assert baseline_cost == result["first_strict_transitions"]
        checked = result["validation"]
        assert len(checked) <= 3
        assert result["validation_transitions"] == sum(item["fixed_prediction_transitions"] for item in checked)
        assert result["total_charged"] == baseline_cost + result["quality_charged"] + result["validation_transitions"]
        assert result["total_charged"] <= cap
        selected = result["selected"]
        assert result["delta_hp"] == selected["resources"]["hp"] - base_hp >= 0
        assert selected["resources"]["potion_slots"] == row["baseline_resources"]["potion_slots"]
        assert selected["resources"]["potions_used"] == []
        if result["quality_status"] == "insufficient_remaining":
            assert not checked and selected["key"] == seed["winner_key"]
            continue
        quality = read(stage / "quality.json.gz")
        assert quality["root_unchanged"]
        assert quality["seed_transitions"] == len(seed["actions"])
        assert quality["transitions"] == quality["seed_transitions"] + sum(
            attempt["transitions"] for attempt in quality["attempts"])
        assert result["quality_observed"] == result["quality_charged"] == quality["transitions"]
        candidates = {candidate["key"]: candidate for candidate in quality["candidates"]}
        assert len(candidates) == len(quality["candidates"])
        comparable = {seed["winner_key"]: base_hp}
        for item in checked:
            candidate = candidates[item["key"]]
            assert item["discovery_transitions"] == baseline_cost + candidate["at"]
            entries = read(OUT / name / item["evidence_origin"] / "native-evidence.json.gz")
            evidence = next(entry["native"] for entry in entries
                            if entry["key"] == item["key"] and entry["stamps"] == candidate["stamps"])
            assert item["status"] == evidence["status"]
            assert item["fixed_prediction_transitions"] == len(candidate["actions"])
            if item["status"] == "win":
                hp = item["resources"]["hp"]
                assert_strict_win(evidence, len(candidate["actions"]), hp)
                if item["comparable_potion_slots"]:
                    assert item["resources"]["potion_slots"] == row["baseline_resources"]["potion_slots"]
                    comparable[item["key"]] = hp
        assert comparable[selected["key"]] == max(comparable.values())
