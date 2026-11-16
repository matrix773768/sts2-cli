"""Regression tests for native save/load behavior."""

from conftest import Game

# These tests require the real engine. Missing DLLs are reported as skips, while
# a present but broken installation must fail rather than silently skip.
from pathlib import Path

import pytest

from save_load_support import assert_same, combat_action

requires_engine = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "lib" / "sts2.dll").is_file(),
    reason="requires native game DLL lib/sts2.dll (M0-A integration not run)",
)



@requires_engine
def test_load_map_save_does_not_retrigger_neow(tmp_path):
    save_path = tmp_path / "map_select.save"

    game = Game()
    try:
        state = game.start(seed="sl1")
        state = game.skip_neow(state)
        assert state["decision"] == "map_select"

        save_result = game.send({"cmd": "write_continue_save", "path": str(save_path)})
        assert save_result["type"] == "save_result"
        assert save_result["success"] is True
    finally:
        game.close()

    game = Game()
    try:
        state = game.send({"cmd": "load_save", "path": str(save_path)})
        assert state["decision"] == "map_select"
    finally:
        game.close()


@requires_engine
def test_load_pre_neow_save_preserves_neow_choice(tmp_path):
    save_path = tmp_path / "pre_neow.save"

    game = Game()
    try:
        state = game.start(seed="sl2")
        assert state["decision"] == "event_choice"

        save_result = game.send({"cmd": "write_continue_save", "path": str(save_path)})
        assert save_result["type"] == "save_result"
        assert save_result["success"] is True
    finally:
        game.close()

    game = Game()
    try:
        state = game.send({"cmd": "load_save", "path": str(save_path)})
        assert state["decision"] == "event_choice"
    finally:
        game.close()




def _decision(state):
    assert state.get("type") == "decision", state
    assert state.get("decision") not in (None, "unknown"), state
    return state


def _snapshot(game, state):
    _decision(state)
    world = game.get_map()
    assert world.get("type") == "map", world
    # Compare the complete returned objects, including optional/new fields.
    # No field removal, sorting of lists, or RNG-result normalization.
    return {"state": state, "map": world}


def _checkpoint(game, path):
    state = game.skip_neow(game.start(seed="m0-a-save-load-1"))
    assert state["decision"] == "map_select", state
    result = game.send({"cmd": "write_continue_save", "path": str(path)})
    assert result.get("type") == "save_result" and result.get("success") is True, result
    assert path.stat().st_size > 0
    return state


def _record_room(game, state, choice):
    """Record entry and every combat action through the first room's outcome."""
    commands = [{"cmd": "action", "action": "select_map_node",
                 "args": {"col": choice["col"], "row": choice["row"]}}]
    snapshots = [_snapshot(game, state)]
    state = _decision(game.send(commands[0]))
    snapshots.append(_snapshot(game, state))
    for _ in range(300):
        if state["decision"] != "combat_play":
            return commands, snapshots
        command = combat_action(state)
        commands.append(command)
        state = _decision(game.send(command))
        snapshots.append(_snapshot(game, state))
    pytest.fail("combat did not finish within 300 actions")


def _replay(path, commands, expected, label):
    game = Game()
    try:
        state = game.send({"cmd": "load_save", "path": str(path)})
        assert_same(expected[0], _snapshot(game, state), f"{label}/0 (load)")
        for step, command in enumerate(commands, 1):
            state = game.send(command)
            assert_same(expected[step], _snapshot(game, state),
                        f"{label}/{step} {command}")
    finally:
        game.close()


@requires_engine
def test_m0a_continuous_matches_reload(tmp_path):
    path = tmp_path / "immutable.save"
    game = Game()
    try:
        state = _checkpoint(game, path)
        original = path.read_bytes()
        monsters = [choice for choice in state["choices"] if choice["type"] == "Monster"]
        assert monsters, "fixed seed must expose a legal Monster node for RNG coverage"
        commands, snapshots = _record_room(game, state, monsters[0])
        assert len(commands) > 2, "must exercise combat actions, not only room entry"
        assert snapshots[1]["state"]["decision"] == "combat_play"
    finally:
        game.close()
    try:
        _replay(path, commands, snapshots, "continuous vs reload")
    finally:
        assert path.read_bytes() == original, "source save was modified"


@requires_engine
def test_m0a_independent_branches_repeat_from_immutable_save(tmp_path):
    path = tmp_path / "immutable.save"
    game = Game()
    try:
        initial = _checkpoint(game, path)
    finally:
        game.close()
    original = path.read_bytes()
    choices = initial["choices"]
    assert len(choices) >= 2, "fixed seed must expose two legal map branches"
    assert (choices[0]["col"], choices[0]["row"]) != (choices[1]["col"], choices[1]["row"])
    # A, B, A: every branch has its own process, including the repeated A.
    recorded = None
    try:
        for index, choice in enumerate(choices[:2]):
            game = Game()
            try:
                state = game.send({"cmd": "load_save", "path": str(path)})
                assert_same(initial, state, f"branch {index}/load")
                assert choice in state["choices"], "branch action must be legal after load"
                commands, snapshots = _record_room(game, state, choice)
                if index == 0:
                    recorded = commands, snapshots
            finally:
                game.close()
            assert path.read_bytes() == original, f"branch {index} changed source save"
        _replay(path, *recorded, "A after B")
    finally:
        assert path.read_bytes() == original, "source save was modified"
