"""Native Ancient healing after the real run_1 act transition."""

from hashlib import sha256
import json
from pathlib import Path

from conftest import Game
from run_route_smoke import action, choose_action
from save_load_support import assert_same
from test_save_load import requires_engine


def save(game, path):
    result = game.send({"cmd": "write_continue_save", "path": str(path)})
    assert result["success"], result
    return json.loads(path.read_bytes())


def enter_ancient(game, state, expected_hp, expected_heal, output):
    (node,) = state["choices"]
    assert node["type"] == "Ancient"
    world = game.get_map()
    children = [n for row in world["rows"] for n in row if n["row"] == node["row"] + 1]
    assert children
    alternate = children[0]
    error = game.act("select_map_node", col=alternate["col"], row=alternate["row"])
    assert error["type"] == "error" and "Ancient" in error["message"]
    assert_same(world, game.get_map(), "blocked Monster preserved map")
    command = action("select_map_node", col=node["col"], row=node["row"])
    event = game.send(command)
    assert event["decision"] == "event_choice" and event["event_name"] == "Orobas", event
    assert event["player"]["hp"] == expected_hp
    assert game.send(command)["type"] == "error"
    trace = [(command, event, game.get_map())]
    state = event
    for _ in range(20):
        if state["decision"] == "map_select":
            break
        command, _ = choose_action(state, None)
        state = game.send(command)
        assert state["type"] == "decision", state
        trace.append((command, state, game.get_map()))
    assert state["decision"] == "map_select", state
    checkpoint = save(game, output)
    history = checkpoint["map_point_history"][1]
    assert len(history) == 1 and history[0]["map_point_type"] == "ancient"
    assert history[0]["player_stats"][0]["hp_healed"] == expected_heal
    return trace, checkpoint


@requires_engine
def test_native_ancient_healing_and_act_start_reload(tmp_path):
    route = Path(__file__).with_name("boss_reward_run_1.jsonl")
    source = tmp_path / "S2.save"
    game = Game()
    try:
        for line in route.read_text(encoding="utf-8").splitlines():
            command = json.loads(line)
            state = game.send(command)
            assert state["type"] == "decision", (command, state)
        assert state["decision"] == "card_reward"
        offering = next(card for card in state["cards"] if card["name"] == "Offering")
        second = game.act("select_card_reward", card_index=offering["index"])
        assert second["context"]["act"] == 2 and second["decision"] == "map_select"
        assert second["player"]["hp"] == state["player"]["hp"] == 8
        world = game.get_map()
        before = save(game, source)
        original = source.read_bytes()
        digest = sha256(original).hexdigest()
        continuous, after = enter_ancient(game, second, 93, 85, tmp_path / "continuous.save")
    finally:
        game.close()

    game = Game()
    try:
        assert sha256(source.read_bytes()).hexdigest() == digest
        loaded = game.send({"cmd": "load_save", "path": str(source)})
        assert_same(second, loaded, "S2 decision")
        assert_same(world, game.get_map(), "S2 map")
        restored = save(game, tmp_path / "loaded.save")
        replay, replay_save = enter_ancient(game, loaded, 93, 85, tmp_path / "replay.save")
        assert_same(continuous, replay, "Ancient replay")
        for field in ("rng", "odds", "map_point_history"):
            assert_same(before[field], restored[field], f"S2 {field}")
            assert_same(after[field], replay_save[field], f"after Ancient {field}")
    finally:
        game.close()
        assert source.read_bytes() == original

    # Construct a later-act A2 checkpoint solely to exercise the native rounding
    # boundary. Missing 84 HP yields 67.2 healing, truncated by the engine.
    a2 = json.loads(original)
    a2["ascension"] = 2
    a2["players"][0]["current_hp"] = 9
    game = Game()
    try:
        loaded = game.send({"cmd": "load_save", "json": json.dumps(a2)})
        assert loaded["player"]["hp"] == 9
        enter_ancient(game, loaded, 76, 67, tmp_path / "a2-after.save")
    finally:
        game.close()
