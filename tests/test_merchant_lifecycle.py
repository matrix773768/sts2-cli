"""Real-route regressions for map recovery and consecutive merchant visits."""

from collections import Counter
from hashlib import sha256
import json
import os
import random
import subprocess

import pytest

from conftest import DOTNET, Game, ROOT
from run_route_smoke import action, choose_action
from save_load_support import assert_same
from test_save_load import requires_engine


GET_MAP = {"cmd": "get_map"}
SECOND_SHOP = {"col": 6, "row": 8}
PROBE_PREFIX = "[SHOPPROBE] "


class Trace:
    def __init__(self, game):
        self.game = game
        self.responses = []

    def send(self, command):
        response = self.game.send(command)
        self.responses.append((command, response))
        return response

    def state_at(self, index):
        # Engine stdout starts with ready, and the probe numbers every JSON line.
        line = index + 2
        entries = self.game.log_dir.joinpath("stderr.log").read_text(encoding="utf-8").splitlines()
        assert not any(entry.startswith("[SHOPPROBE-ERROR]") for entry in entries), self.game.log_dir
        for entry in entries:
            if entry.startswith(PROBE_PREFIX):
                state = json.loads(entry[len(PROBE_PREFIX):])
                if state.pop("line") == line:
                    return state
        pytest.fail(f"Missing native state for response {line}: {self.game.log_dir}")


def drive(trace, state, rng, destination):
    """Follow the bounded C1 policy from a real route state."""
    for _ in range(200):
        assert state["type"] == "decision", state
        command, node = choose_action(state, rng)
        state = trace.send(command)
        assert state["type"] == "decision", (command, state)
        if node:
            world = trace.send(GET_MAP)
            coord = {key: node[key] for key in ("col", "row")}
            assert world["type"] == "map" and world["current_coord"] == coord, world
            if coord == destination:
                return state, world
    pytest.fail(f"Did not reach {destination}: {trace.game.log_dir}")


def buy(trace, state, items, resource, name, index_key):
    purchaseable = [item for item in state[items]
                    if item["is_stocked"] and item["cost"] <= state["player"]["gold"]]
    entry = min(purchaseable, key=lambda item: (item["cost"], item["index"]))
    command = action(name, **{index_key: entry["index"]})
    after = trace.send(command)
    assert after["decision"] == "shop", after
    assert after["player"]["gold"] == state["player"]["gold"] - entry["cost"]
    assert after[items][entry["index"]]["is_stocked"] is False
    resources = Counter(item["name"] for item in state["player"][resource])
    resources[entry["name"]] += 1
    assert Counter(item["name"] for item in after["player"][resource]) == resources
    assert trace.send(command)["type"] == "error"
    return after


@pytest.fixture(scope="module")
def merchant_route(tmp_path_factory):
    work = tmp_path_factory.mktemp("merchant-route")
    probe = ROOT / "tests/ShopStateProbe/ShopStateProbe.csproj"
    result = subprocess.run([DOTNET, "build", str(probe), "--output", str(work / "probe")],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    path = work / "S.save"
    with pytest.MonkeyPatch.context() as config:
        hooks = os.environ.get("DOTNET_STARTUP_HOOKS")
        hook = str(work / "probe/ShopStateProbe.dll")
        config.setenv("DOTNET_STARTUP_HOOKS", os.pathsep.join((hooks, hook)) if hooks else hook)
        continuous = Trace(Game())
        try:
            start = {"cmd": "start_run", "seed": "run_3", "character": "Ironclad",
                     "ascension": 0, "lang": "en"}
            rng = random.Random("run_3")
            first, _ = drive(continuous, continuous.send(start), rng, {"col": 4, "row": 4})
            assert first["decision"] == "shop", first
            first_index = len(continuous.responses) - 2
            checkpoint = continuous.send(action("leave_room"))
            departed_index = len(continuous.responses) - 1
            assert checkpoint["decision"] == "map_select", checkpoint
            assert_same(checkpoint, continuous.send(action("leave_room")), "repeated leave")
            checkpoint_map = continuous.send(GET_MAP)
            assert checkpoint_map["current_coord"] == {"col": 4, "row": 4}
            saved = continuous.send({"cmd": "write_continue_save", "path": str(path)})
            assert saved["type"] == "save_result" and saved["success"], saved
            original = path.read_bytes()
            digest = sha256(original).hexdigest()
            first_future_index = len(continuous.responses)
            second, _ = drive(continuous, checkpoint, rng, SECOND_SHOP)
            assert second["decision"] == "shop", second
            second_index = len(continuous.responses) - 2
            future = continuous.responses[first_future_index:]
            assert path.read_bytes() == original

            pending = continuous.send(action("remove_card"))
            assert pending["decision"] == "card_select", pending
            assert pending["min_select"] == pending["max_select"] == 1
            blocked_leave = continuous.send(action("leave_room"))
            assert blocked_leave["type"] == "error" and "pending shop" in blocked_leave["message"]
            removed = pending["cards"][0]
            after = continuous.send(action("select_cards", indices=str(removed["index"])))
            assert after["decision"] == "shop", after
            removal_index = len(continuous.responses) - 1
            assert after["player"]["gold"] == second["player"]["gold"] - second["card_removal_cost"]
            expected_deck = Counter(card["id"] for card in second["player"]["deck"])
            expected_deck[removed["id"]] -= 1
            assert Counter(card["id"] for card in after["player"]["deck"]) == +expected_deck
            assert after["player"]["gold"] >= second["card_removal_cost"]
            duplicate = continuous.send(action("remove_card"))
            duplicate_index = len(continuous.responses) - 1
            after_card = buy(continuous, after, "cards", "deck", "buy_card", "card_index")
            buy(continuous, after_card, "potions", "potions", "buy_potion", "potion_index")
        finally:
            continuous.game.close()

        replay = Trace(Game())
        try:
            assert sha256(path.read_bytes()).hexdigest() == digest
            assert path.read_bytes() == original
            replay.send({"cmd": "load_save", "path": str(path), "lang": "en"})
            replay.send(GET_MAP)
            for command, _ in future:
                replay.send(command)
            if replay.responses[-2][1].get("decision") == "shop":
                for command, _ in continuous.responses[second_index + 2:]:
                    replay.send(command)
        finally:
            replay.game.close()
            assert sha256(path.read_bytes()).hexdigest() == digest
            assert path.read_bytes() == original
    return (continuous, replay, json.loads(original), checkpoint, checkpoint_map, future,
            first_index, departed_index, second_index, removal_index, duplicate_index, after, duplicate)


@requires_engine
def test_shop_checkpoint_preserves_unknown_node_replay(merchant_route):
    continuous, replay, save, checkpoint, world, future, _, _, second, *_ = merchant_route
    assert_same(checkpoint, replay.responses[0][1], "loaded decision")
    assert_same(world, replay.responses[1][1], "loaded map")
    future_end = len(future) + 2
    assert len(replay.responses) >= future_end
    for index, ((command, expected), (replayed, actual)) in enumerate(zip(future, replay.responses[2:future_end]), 1):
        assert command == replayed
        assert_same(expected, actual, f"future step {index}: {command}; logs={replay.game.log_dir}")
    assert replay.responses[future_end - 2][1]["decision"] == "shop"
    assert_same(continuous.responses[second + 2:], replay.responses[future_end:],
                "purchases and rejected repeats after reload")
    odds = {kind: save["odds"][f"unknown_map_point_{kind}_odds_value"]
            for kind in ("monster", "elite", "shop", "treasure")}
    assert_same(odds, replay.state_at(0)["unknownOdds"], "loaded native odds")
    assert replay.state_at(0)["count"] == 0
    assert replay.state_at(future_end - 2)["count"] == 1
    assert replay.state_at(future_end - 2)["matchingPlayer"] is True
    assert "Entered a merchant while a merchant was already active!" not in (
        replay.game.log_dir / "stderr.log").read_text(encoding="utf-8")


@requires_engine
def test_consecutive_shops_finalize_first_visit(merchant_route):
    continuous, _, save, _, _, _, first, departed, second, *_ = merchant_route
    assert continuous.state_at(first)["count"] == 1
    assert continuous.state_at(departed)["count"] == 0
    assert continuous.state_at(second)["count"] == 1
    assert continuous.state_at(second)["inventoryTag"] != continuous.state_at(first)["inventoryTag"]
    assert continuous.state_at(second)["matchingPlayer"] is True
    assert "Entered a merchant while a merchant was already active!" not in (
        continuous.game.log_dir / "stderr.log").read_text(encoding="utf-8")
    history = save["map_point_history"][0]
    first_shop = history[-1]
    assert first_shop["map_point_type"] == "shop"
    stats = first_shop["player_stats"][0]
    assert len(stats["card_choices"]) == 7
    assert len(stats["relic_choices"]) == len(stats["potion_choices"]) == 3
    assert not any(choice["was_picked"] for category in ("card_choices", "relic_choices", "potion_choices")
                   for choice in stats[category])


@requires_engine
def test_sold_out_removal_unavailable_with_enough_gold(merchant_route):
    continuous, _, _, _, _, _, _, _, _, removal, repeated, after, duplicate = merchant_route
    assert continuous.state_at(removal)["removalStocked"] is False
    assert after.get("card_removal_cost") is None
    assert duplicate["type"] == "error" and duplicate["message"] == "No card removal available"
    assert_same(continuous.state_at(removal), continuous.state_at(repeated),
                "rejected repeat removal left state unchanged")
