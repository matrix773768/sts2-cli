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


@pytest.mark.parametrize("decision", ["card_select", "bundle_select", "event_choice",
                                      "rest_site", "shop", "unknown"])
def test_pending_or_unexpected_decision_is_not_combat_end(decision):
    from test_save_load import _assert_room_outcome
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _assert_room_outcome({"type": "decision", "decision": decision}, 3)


@pytest.mark.parametrize("state", [
    {"type": "error", "error_code": "combat_turn_timeout"},
    {"type": "decision", "decision": "card_reward", "from_event": True},
    {"type": "decision", "decision": "game_over", "victory": True},
    {"type": "decision", "decision": "game_over", "victory": False, "player": {"hp": 20}},
])
def test_invalid_outcome_rejected(state):
    from test_save_load import _assert_room_outcome
    with pytest.raises(AssertionError):
        _assert_room_outcome(state, 3)


@pytest.mark.parametrize("state", [
    {"type": "decision", "decision": "card_reward", "cards": [{"index": 0}],
     "gold_earned": 10, "player": {"hp": 20}},
    {"type": "decision", "decision": "map_select", "choices": [{"col": 1}], "player": {"hp": 20}},
    {"type": "decision", "decision": "game_over", "victory": False, "player": {"hp": 0}},
])
def test_explicit_outcomes_require_combat_depth(state):
    from test_save_load import _assert_room_outcome
    _assert_room_outcome(state, 2)
    with pytest.raises(AssertionError, match="at least two combat actions"):
        _assert_room_outcome(state, 1)


def test_record_room_rejects_pending_selection_after_combat_action():
    from test_save_load import _record_room
    choice = {"col": 1, "row": 1, "type": "Monster"}
    combat = {"type": "decision", "decision": "combat_play", "hand": [], "energy": 0}

    class FakeGame:
        sent = []

        def send(self, command):
            self.sent.append(command)
            if len(self.sent) == 1:
                return combat
            if len(self.sent) == 2:
                return combat
            return {"type": "decision", "decision": "card_select"}

        def get_map(self):
            return {"type": "map", "current_coord": {"col": 1, "row": 1}}

    game = FakeGame()
    with pytest.raises(pytest.fail.Exception, match="unsupported pending choice.*card_select"):
        _record_room(game, {"type": "decision", "decision": "map_select", "choices": [choice]}, choice)
    assert len(game.sent) == 3


def test_replay_rejects_truncated_trace_before_starting_process(monkeypatch):
    import test_save_load as integration

    def unexpected_process():
        pytest.fail("invalid trace must be rejected before process creation")

    monkeypatch.setattr(integration, "Game", unexpected_process)
    with pytest.raises(AssertionError, match="trace length mismatch"):
        integration._replay("source.save", [{"cmd": "action"}], [{}], "A")


def test_record_room_rejects_ignored_map_action():
    from test_save_load import _record_room
    choice = {"col": 1, "row": 1, "type": "Monster"}

    class FakeGame:
        def send(self, command):
            return {"type": "decision", "decision": "combat_play"}

        def get_map(self):
            return {"type": "map", "current_coord": {"col": 0, "row": 0}}

    with pytest.raises(AssertionError, match="room entry coordinate"):
        _record_room(FakeGame(), {"type": "decision", "decision": "map_select", "choices": [choice]}, choice)
