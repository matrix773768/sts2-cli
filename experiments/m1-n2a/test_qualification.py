from collections import Counter
from dataclasses import FrozenInstanceError
import gzip
import json
from pathlib import Path

import pytest

from environment import Observation, choose

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def test_wire_allowlist_and_immutable_records():
    wire = read("mechanics.json")["wire"]
    assert set(wire) == {"turn", "hp", "block", "energy", "draw_count", "hand", "enemies", "actions"}
    assert all(set(row) == {"index", "id", "upgrade"} for row in wire["hand"])
    assert all(set(row) == {"index", "hp", "block"} for row in wire["enemies"])
    assert all(set(row) <= {"index", "card", "target", "cost"} for row in wire["actions"])
    obs = Observation.decode(wire | {"rng": [5], "continuation": "ignored"})
    assert choose(obs, obs.actions, False) in obs.actions
    with pytest.raises(FrozenInstanceError):
        obs.hand[0].upgrade = 1


def test_invalid_actions_and_dynamic_cost():
    data = read("mechanics.json")
    assert len(data["rejections"]) == 2
    assert data["before_diff"] == data["after_diff"] == {}
    assert {cost for card, cost in data["native"][0]["hand"] if card == "CARD.STOMP"} == {3}
    assert {cost for card, cost in data["native"][1]["hand"] if card == "CARD.STOMP"} == {2}
    assert all(action["cost"] == 2 for action in data["after"]["actions"] if action["card"] is not None)


def test_repeated_episodes_and_worker_qualification():
    with gzip.open(HERE / "benchmark.json.gz", "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    assert {r["case"]["split"] for r in data["inputs"]} == {"development"}
    assert {x["loaded"]["sha256"] for x in data["lifecycle"]} == {data["versions"]["solver_sha256"]}
    assert Counter(r["phase"] for r in data["rows"]) == {"cold": 4, "same": 32, "mixed": 128}
    seen = {}
    for row in data["rows"]:
        terminal = {k: v for k, v in row["terminal"].items() if not k.endswith("_ms")}
        key = row["id"], row["defense_first"]
        assert seen.setdefault(key, (row["trajectory"], terminal)) == (row["trajectory"], terminal)
        assert terminal["actions"] <= terminal["transitions"] <= 48
        assert terminal["result"]["evidence"] == "prediction_only"
        if terminal["status"] == "unsupported":
            assert terminal["result"]["boundary"] == "PendingChoice"
        assert 0 < row["working_set"] < 448 * 1024**2
        assert 0 < row["memory"] < 448 * 1024**2
    same = [r for r in data["rows"] if r["phase"] == "same"]
    assert [r["defense_first"] for r in same[:3]] == [False, True, False]
    assert same[0]["trajectory"] != same[1]["trajectory"]
    assert same[0]["trajectory"] == same[2]["trajectory"]


def test_independent_native_differences_remain_visible():
    rows = read("native-audit.json")["rows"]
    assert [(r["status"], r["checked"]) for r in rows] == [
        ("terminal_difference", 8), ("terminal_difference", 15),
        ("public_and_outcome_match", 11), ("prediction_boundary", 8),
    ]
    for row in rows[:2]:
        assert row["expected"]["hp"] == row["native"]["hp"]
        assert row["expected"]["gold"] != row["native"]["gold"]
        assert row["expected"]["potions"] != row["native"]["potions"]
        assert row["evidence"] == "public_diff_only"
