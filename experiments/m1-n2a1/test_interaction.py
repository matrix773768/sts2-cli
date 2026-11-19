"""Qualification regressions over immutable policy data and engine evidence."""
from dataclasses import FrozenInstanceError
import gzip
import json
from pathlib import Path

import pytest

from interaction import Observation, feedback, reward

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def test_feedback_uses_only_locked_combat_and_preserves_missing_outcomes():
    win = feedback(dict(status="predicted_win", result={"hp": 1, "max_hp": 80, "gold": 99}))
    death = feedback(dict(status="death", result={"hp": 0, "max_hp": 80}))
    assert win["post_reward"] == {"executed": False, "resources": None}
    assert reward(win, "survival_only") == 1
    assert reward(death, "survival_only") == 0
    assert reward(win, "win_then_hp") > reward(death, "win_then_hp")
    for status in ("unsupported", "truncated", "invalid_action", "execution_fault"):
        unknown = feedback(dict(status=status, detail="missing"))
        assert unknown["missing_reason"] == "missing"
        assert unknown["combat_terminal"] is None
        assert reward(unknown, "win_then_hp") is None


def test_public_choice_and_exact_duplicate_native_binding():
    data = read("duplicate.json")
    a, b, repeated = data["variants"]
    assert a == repeated
    assert a["plan"]["choice"]["cards"][0]["state_key"] == b["plan"]["choice"]["cards"][0]["state_key"]
    assert [r["plan"]["choice"]["cards"][0]["option_occurrence"] for r in (a, b)] == [0, 1]
    assert all(n["choices"][0]["verified"] and n["choices"][0]["state_match"] for n in data["native"])
    obs = Observation.decode(a["observation"] | {"audit_stamp": a["stamp"], "rng": [1, 2, 3]})
    assert not hasattr(obs, "audit_stamp") and not hasattr(obs, "rng")
    assert all(not hasattr(x.choice, "state_key") for x in obs.actions if x.choice)
    with pytest.raises(FrozenInstanceError):
        obs.actions[0].cost = 0


def test_native_observation_and_dynamic_cost():
    audit = read("native-audit.json")
    assert sum(r["count"] for r in audit["original_stops"]) == 43
    assert sum(r["checked"] for r in audit["rows"]) == 155
    assert all(not r["diffs"] for r in audit["rows"])
    assert all(choice["state_match"] for r in audit["rows"] for choice in r["choices"])
    for row in audit["rows"]:
        if row["status"] == "win":
            assert row["native_locked"]["player_gold"] == row["predicted_terminal"]["gold"]
            assert row["native_after_combat"]["reward_action_executed"] is False
    mechanics = read("mechanics.json")
    assert not mechanics["diffs"]
    for key, cost in (("before", 3), ("after", 2)):
        obs = Observation.decode(mechanics[key])
        assert {a.cost for a in obs.actions if a.card is not None and obs.hand[a.card].id == "STOMP"} == {cost}


def test_frozen_workload_feedback_and_typed_stops():
    with gzip.open(HERE / "benchmark.json.gz", "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    assert data["batches"]["mixed"]["stops"] == {"predicted_win": 85, "death": 32, "truncated": 11}
    assert len(data["rows"]) == 164
    assert {r["loaded"]["sha256"] for r in data["lifecycle"]} == {data["versions"]["solver_sha256"]}
    baseline = {}
    for row in data["rows"]:
        terminal = row["terminal"]
        observation = row["trajectory"][0]["observation"]
        assert "audit_stamp" not in observation
        assert terminal["feedback"]["post_reward"]["resources"] is None
        assert (reward(terminal["feedback"], "survival_only") is None) == (terminal["status"] == "truncated")
        semantic = row["trajectory"], {k: v for k, v in terminal.items() if not k.endswith("_ms")}
        assert baseline.setdefault((row["id"], row["defense_first"]), semantic) == semantic
