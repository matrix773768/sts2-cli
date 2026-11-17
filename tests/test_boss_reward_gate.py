"""Replay the real run_1 route to exercise the boss reward boundary."""
import json
from pathlib import Path

import pytest

from conftest import Game
from save_load_support import assert_same
from test_save_load import requires_engine


@requires_engine
@pytest.mark.parametrize("take_reward", [True, False], ids=["claim", "skip"])
def test_boss_reward_blocks_early_transition(take_reward):
    route = Path(__file__).with_name("boss_reward_run_1.jsonl")
    game = Game()
    try:
        for line in route.read_text(encoding="utf-8").splitlines():
            command = json.loads(line)
            pending = game.send(command)
            assert pending["type"] == "decision", (command, pending, game.log_dir)
        assert pending["decision"] == "card_reward"
        assert (pending["context"]["act"], pending["context"]["floor"],
                pending["context"]["room_type"]) == (1, 17, "Boss")
        world = game.get_map()
        offering = next(card for card in pending["cards"] if card["name"] == "Offering")
        for action in ("proceed", "proceed", "leave_room", "select_map_node"):
            response = game.act(action, col=0, row=0) if action == "select_map_node" else game.act(action)
            assert_same(pending, response, f"{action} during Boss reward; logs={game.log_dir}")
            assert_same(world, game.get_map(), f"{action} preserved the map")

        assert_same(pending, game.enter_room("shop"), "debug room entry preserved the reward")
        assert_same(world, game.get_map(), "debug room entry preserved the map")

        if take_reward:
            next_state = game.act("select_card_reward", card_index=offering["index"])
        else:
            assert pending["can_skip"]
            next_state = game.act("skip_card_reward")
        assert next_state["decision"] == "map_select", next_state
        assert next_state["context"]["act"] == 2
        before, after = pending["player"], next_state["player"]
        assert after["deck_size"] == before["deck_size"] + int(take_reward)
        if take_reward:
            assert after["deck"][-1]["id"] == offering["id"]
        for key in ("gold", "relics", "potions"):
            assert_same(before.get(key), after.get(key), f"no duplicate {key}")
        next_map = game.get_map()
        assert_same(next_state, game.act("proceed"), "proceed after transition")
        assert_same(next_map, game.get_map(), "no second transition")
    finally:
        game.close()
