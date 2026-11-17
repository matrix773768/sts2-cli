"""Verify an immutable checkpoint made after taking a combat reward."""

from collections import Counter
from hashlib import sha256
import json

import pytest

from conftest import Game
from save_load_support import assert_same, combat_action
from test_save_load import requires_engine


def exchange(game, command):
    try:
        result = game.send(command)
    except (RuntimeError, TimeoutError) as error:
        raise AssertionError(
            f"Command could not complete: {command!r}; logs={game.log_dir}"
        ) from error
    expected_type = {
        "get_map": "map",
        "write_continue_save": "save_result",
    }.get(command["cmd"], "decision")
    assert result.get("type") == expected_type, (
        f"Command failed: {command!r}, expected {expected_type}, "
        f"actual {result!r}; logs={game.log_dir}"
    )
    assert result.get("decision") != "unknown", (
        f"Unknown decision: {command!r}, actual {result!r}; logs={game.log_dir}"
    )
    return result


def action(name, **args):
    return {"cmd": "action", "action": name, "args": args}


def snapshot(game, state):
    return {"state": state, "map": exchange(game, {"cmd": "get_map"})}


def reward_command(state):
    card = state["cards"][0]
    return action("select_card_reward", card_index=card["index"])


def interaction(state):
    decision = state["decision"]
    if decision == "combat_play":
        return combat_action(state)
    if decision == "card_reward" and state["cards"]:
        return reward_command(state)
    if decision == "card_select":
        count = state["min_select"]
        if count == 0:
            return action("skip_select")
        assert len(state["cards"]) >= count, state
        return action("select_cards", indices=",".join(
            str(card["index"]) for card in state["cards"][:count]
        ))
    if decision in ("event_choice", "rest_site"):
        option = next((o for o in state["options"]
                       if not o.get("is_locked") and o.get("is_enabled", True)), None)
        assert option is not None, f"No legal option: {state!r}"
        return action("choose_option", option_index=option["index"])
    if decision == "bundle_select":
        return action("select_bundle", bundle_index=0)
    if decision == "shop":
        return action("leave_room")
    raise AssertionError(f"Cannot continue from decision {state!r}")


def ordered_choices(state):
    return sorted(state["choices"], key=lambda node: node["type"] != "Monster")


def coord(node):
    return {key: node[key] for key in ("col", "row")}


def trace_to_combat_reward(game, initial, first_node, label):
    """Traverse legal rooms until a real Monster reward has been consumed."""
    commands, snapshots, rooms = [], [initial], []
    played = 0
    combat_reward = False
    for _ in range(300):
        state = snapshots[-1]["state"]
        decision = state["decision"]
        if decision == "map_select":
            if combat_reward:
                assert state["context"]["room_type"] == "Map", state
                return commands, snapshots, rooms, played
            choices = ordered_choices(state)
            assert choices, f"{label}: map has no legal continuation"
            node = first_node if not rooms else choices[0]
            assert node in choices, f"{label}: illegal room choice {node!r}"
            command = action("select_map_node", **coord(node))
        else:
            command = interaction(state)

        response = exchange(game, command)
        result = snapshot(game, response)
        if decision == "map_select":
            assert_same(coord(node), result["map"]["current_coord"], f"{label} room entry")
            rooms.append(node)
            if node["type"] == "Monster":
                assert response["decision"] == "combat_play", response
        if decision == "combat_play":
            played += 1
        if (decision == "card_reward" and not state.get("from_event", False)
                and rooms[-1]["type"] == "Monster"):
            assert "gold_earned" in state and played >= 2, state
            card_id = state["cards"][0]["id"]
            before = Counter(card["id"] for card in state["player"]["deck"])
            after = Counter(card["id"] for card in response["player"]["deck"])
            assert after[card_id] == before[card_id] + 1, (
                f"{label}: reward {card_id} did not enter deck after {command!r}; "
                f"expected {before[card_id] + 1}, actual {after[card_id]}; "
                f"logs={game.log_dir}"
            )
            combat_reward = True
        commands.append(command)
        snapshots.append(result)
    raise AssertionError(f"{label}: no post-reward map within 300 commands; logs={game.log_dir}")


def check_unchanged(path, original, expected_hash, stage):
    actual = path.read_bytes()
    actual_hash = sha256(actual).hexdigest()
    assert actual_hash == expected_hash and actual == original, (
        f"{stage}: S1 changed, expected SHA-256 {expected_hash}, actual {actual_hash}"
    )
    print(f"{stage}: S1 SHA-256 {actual_hash}", flush=True)


def from_save(path, original, expected_hash, expected, label, run):
    game = Game()
    print(f"{label}: logs={game.log_dir}", flush=True)
    try:
        check_unchanged(path, original, expected_hash, f"{label} before load")
        state = exchange(game, {"cmd": "load_save", "path": str(path)})
        loaded = snapshot(game, state)
        assert_same(expected, loaded, f"{label}/0 load_save")
        return run(game, loaded)
    finally:
        try:
            game.close()
        finally:
            check_unchanged(path, original, expected_hash, f"{label} after execution")


def replay(game, commands, expected, label):
    assert len(expected) == len(commands) + 1
    for index, (command, wanted) in enumerate(zip(commands, expected[1:]), 1):
        response = exchange(game, command)
        assert_same(wanted, snapshot(game, response), f"{label}/{index} {command!r}")


def report_trace(label, trace):
    commands, _, rooms, played = trace
    print(f"{label}: rooms={rooms!r}, commands={len(commands)}, combat_actions={played}",
          flush=True)


@pytest.fixture(scope="module")
def post_reward_checkpoint(tmp_path_factory):
    path = tmp_path_factory.mktemp("m0a2") / "S1.save"
    game = Game()
    print(f"Continuous: logs={game.log_dir}", flush=True)
    try:
        initial = snapshot(game, game.skip_neow(game.start(seed="m0-a-save-load-1")))
        assert initial["state"]["decision"] == "map_select", initial["state"]
        initial_monsters = [node for node in initial["state"]["choices"]
                            if node["type"] == "Monster"]
        assert initial_monsters, "Initial map must offer a legal Monster node"
        first_node = initial_monsters[0]
        first = trace_to_combat_reward(game, initial, first_node, "Before S1")
        report_trace("Before S1", first)
        checkpoint = first[1][-1]
        player = checkpoint["state"]["player"]
        resources = {key: player[key] for key in ("hp", "max_hp", "gold", "deck", "relics", "potions")}
        assert checkpoint["map"]["current_coord"] == coord(first_node)
        visited = [coord(node) for row in checkpoint["map"]["rows"]
                   for node in row if node["visited"]]
        assert coord(first_node) in visited, visited
        assert player["deck_size"] > initial["state"]["player"]["deck_size"]
        result = exchange(game, {"cmd": "write_continue_save", "path": str(path)})
        assert result["success"] is True and path.is_file() and path.stat().st_size > 0, result
        original = path.read_bytes()
        expected_hash = sha256(original).hexdigest()
        choices = ordered_choices(checkpoint["state"])
        print("S1 " + json.dumps({
            "bytes": len(original), "sha256": expected_hash, "resources": resources,
            "current_coord": checkpoint["map"]["current_coord"], "visited": visited,
            "choices": choices,
        }, ensure_ascii=False), flush=True)
        assert choices, "S1 must have a legal continuation"
        try:
            continuous = trace_to_combat_reward(game, checkpoint, choices[0], "Continuous after S1")
            report_trace("Continuous after S1", continuous)
        finally:
            check_unchanged(path, original, expected_hash, "Continuous after execution")
    finally:
        game.close()

    return path, original, expected_hash, checkpoint, choices, continuous


@requires_engine
def test_m0a2_post_reward_checkpoint_replays_across_rooms(post_reward_checkpoint):
    path, original, expected_hash, checkpoint, _, continuous = post_reward_checkpoint
    from_save(path, original, expected_hash, checkpoint, "Continuous vs reload",
              lambda g, _: replay(g, continuous[0], continuous[1], "Continuous vs reload"))


@requires_engine
def test_m0a2_post_reward_checkpoint_independent_branches(post_reward_checkpoint):
    path, original, expected_hash, checkpoint, choices, _ = post_reward_checkpoint
    if len({(node["col"], node["row"]) for node in choices}) < 2:
        pytest.skip("S1 has fewer than two legal continuations for A/B/A")

    branch_a = from_save(path, original, expected_hash, checkpoint, "A",
                         lambda g, s: trace_to_combat_reward(g, s, choices[0], "A"))
    report_trace("A", branch_a)
    branch_b = from_save(path, original, expected_hash, checkpoint, "B",
                         lambda g, s: trace_to_combat_reward(g, s, choices[1], "B"))
    report_trace("B", branch_b)
    from_save(path, original, expected_hash, checkpoint, "A after B",
              lambda g, _: replay(g, branch_a[0], branch_a[1], "A after B"))
    report_trace("A after B", branch_a)
