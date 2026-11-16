"""Engine-free checks of the M0-A comparison and action helpers."""
import pytest

from save_load_support import assert_same, combat_action, first_difference


@pytest.mark.parametrize("left,right,field", [
    ({"player": {"hp": 70}}, {"player": {"hp": 69}}, "$.player.hp"),
    ({"deck": ["a", "b"]}, {"deck": ["b", "a"]}, "$.deck[0]"),
    ({"optional": None}, {}, "$.optional"),
    ({}, {"new_rng_result": 3}, "$.new_rng_result"),
    ([1], [1, 2], "$.length"),
    (1, True, "$"),
])
def test_difference_reports_field_and_values(left, right, field):
    with pytest.raises(AssertionError, match="step replay/7") as error:
        assert_same(left, right, "replay/7")
    assert field in str(error.value)
    assert "expected" in str(error.value) and "actual" in str(error.value)


def test_equal_nested_objects_and_first_difference():
    assert first_difference({"x": [None, {"y": 2}]}, {"x": [None, {"y": 2}]}) is None
    assert first_difference({"a": 1, "b": 2}, {"b": 4, "a": 3}).startswith("$.a:")


def test_combat_uses_legal_card_and_live_target():
    state = {"decision": "combat_play", "energy": 1,
             "hand": [{"index": 4, "can_play": False, "cost": 0},
                      {"index": 7, "can_play": True, "cost": 1, "target_type": "AnyEnemy"}],
             "enemies": [{"index": 0, "hp": 0}, {"index": 3, "hp": 12}]}
    assert combat_action(state) == {"cmd": "action", "action": "play_card",
                                     "args": {"card_index": 7, "target_index": 3}}
    state["energy"] = 0
    assert combat_action(state) == {"cmd": "action", "action": "end_turn"}


def test_replay_reports_first_bad_step_and_closes_process(monkeypatch):
    import test_save_load as integration

    initial = {"type": "decision", "decision": "map_select"}
    later = {"type": "decision", "decision": "combat_play", "player": {"hp": 50}}
    world = {"type": "map", "current_coord": None}
    commands = [{"cmd": "action", "action": "end_turn"}]
    expected = [{"state": initial, "map": world}, {"state": later, "map": world}]

    class FakeGame:
        closed = False
        sent = []

        def send(self, command):
            self.sent.append(command)
            if command["cmd"] == "load_save":
                return initial
            return {**later, "player": {"hp": 49}}

        def get_map(self):
            return world

        def close(self):
            self.closed = True

    fake = FakeGame()
    monkeypatch.setattr(integration, "Game", lambda: fake)
    with pytest.raises(AssertionError, match=r"A/1.*\$.state.player.hp: expected 50, actual 49"):
        integration._replay("source.save", commands, expected, "A")
    assert fake.closed
    assert fake.sent == [{"cmd": "load_save", "path": "source.save"}, *commands]
