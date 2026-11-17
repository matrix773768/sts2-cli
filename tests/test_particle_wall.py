"""Replay the original legal Regent routes through returning Particle Wall."""
import json
from pathlib import Path

import pytest

from test_save_load import requires_engine


@requires_engine
@pytest.mark.parametrize(("seed", "count", "floor", "round_number", "stars", "block"),
                         [("run_1", 33, 3, 2, 3, 5), ("run_4", 134, 12, 4, 2, 0)])
def test_particle_wall_native_play(game, seed, count, floor, round_number, stars, block):
    path = Path(__file__).with_name(f"particle_wall_{seed}.jsonl")
    commands = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(commands) == count
    for command in commands[:-1]:
        state = game.send(command)
        assert state["type"] == "decision", (command, state)

    index = commands[-1]["args"]["card_index"]
    card = state["hand"][index]
    assert card["id"] == "CARD.PARTICLE_WALL" and card["can_play"]
    assert card["star_cost"] == 2
    assert (state["context"]["floor"], state["round"], state["energy"]) == (floor, round_number, 0)
    assert (state["stars"], state["player"]["block"]) == (stars, block)

    result = game.send(commands[-1])
    assert result["decision"] == "combat_play", result
    assert result["hand"][index]["id"] == card["id"]
    assert result["energy"] == 0
    assert result["stars"] == stars - 2
    assert result["player"]["block"] == block + 9

    rejected = game.send(commands[-1])
    assert rejected["type"] == "error" and "Cannot play card" in rejected["message"], rejected
