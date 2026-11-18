"""Verify all six raw native outcomes and the two compatibility boundaries."""
import gzip
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("STS2_F3DB_RESULTS", HERE.parents[1] / "logs/m1-f3d-b/formal"))
EXPECTED = {
    "strength-early": (40, 10),
    "block-hive-stocked": (33, 33),
    "poison-early": (56, 11),
    "shiv-lean": (18, 18),
    "shiv-hive-stocked": (26, 26),
    "strength-hive-low": (73, 24),
}


@pytest.fixture(scope="module")
def evidence():
    return json.loads((WORK / "results.json").read_bytes())["cases"]


def trials(name, row):
    with gzip.open(WORK / name / row["cell"]["history"], "rt", encoding="utf-8") as stream:
        return json.load(stream)


def test_frozen_cohort_has_strict_native_wins(evidence):
    assert set(evidence) == set(EXPECTED)
    for name, (used, actions) in EXPECTED.items():
        row = evidence[name]
        cell = row["cell"]
        runs = trials(name, row)
        assert cell["arm"] == "C" and not cell["potions"]
        assert cell["status"] == "native_win"
        assert used == cell["used"] == sum(r["transitions"] for r in runs) <= 128
        accepted = runs[-1]["verification"]
        assert accepted["status"] == "win" and accepted["strict_terminal"]
        assert accepted["matched_actions"] == len(accepted["trace"]) == actions
        assert accepted["native_final"]["outcome"]["final_enemy_hp"] == 0
        assert all(s["actual_sha256"] == s["expected_sha256"] for s in accepted["trace"])


@pytest.mark.parametrize(("name", "rejections", "step"), [("strength-early", 1, 15), ("poison-early", 2, 9)])
def test_raw_enemy_side_terminal_difference_stays_rejected(evidence, name, rejections, step):
    rs = trials(name, evidence[name])
    assert len(rs) == rejections + 1
    for trial in rs[:-1]:
        native = trial["verification"]
        assert native["status"] == "prediction_mismatch" and not native["strict_terminal"]
        assert native["matched_actions"] == step - 1 and native["first_difference"]["phase"] == step
        observed = native["trace"][-1]
        assert observed["terminal"] and observed["native_action"]["action"] == "end_turn"
        assert observed["actual_sha256"] != observed["expected_sha256"]
        before, after = observed["before_window"], observed["terminal_window"]
        assert (before["side"], after["side"]) == ("Player", "Enemy")
        assert all(before[k] == after[k] for k in ("round", "card_plays", "card_draws"))
        assert before["plays_in_window"] > 0 and after["plays_in_window"] == 0
        assert before["enemy_hp"] > 0 and after["enemy_hp"] == 0
    assert rs[-1]["winner_key"] not in {r["winner_key"] for r in rs[:-1]}


def test_neutralize_guard_and_native_card_step(evidence):
    row = evidence["poison-early"]
    assert row["native_neutralize"] and "NeutralizePrefix" in row["patch_guard"]["detail"]
    assert all(not r["native_neutralize"] for name, r in evidence.items() if name != "poison-early")
    winner = trials("poison-early", row)[-1]
    assert winner["actions"][2]["card_id"] == "NEUTRALIZE"
    step = winner["verification"]["trace"][2]
    assert step["native_action"]["action"] == "play_card"
    assert step["actual_sha256"] == step["expected_sha256"]
