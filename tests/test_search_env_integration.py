"""Real-engine acceptance for the M1-B1 search environment."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

import search_env

from search_env import CheckpointError, ReplayMismatch, SearchEnv
from test_save_load import requires_engine
from test_save_load_cross_room import action, coord, interaction


def assert_unchanged(checkpoint, original):
    assert checkpoint.path.read_bytes() == original
    assert sha256(original).hexdigest() == checkpoint.sha256


@pytest.fixture
def root(tmp_path):
    with SearchEnv(game_build="26660232", checkpoint_dir=tmp_path / "checkpoints",
                   log_root=tmp_path / "engines") as env:
        state = env.reset(seed="m0-a-save-load-1")
        commands = env._engine.log_dir / "commands.jsonl"
        before = commands.read_bytes()
        with pytest.raises(CheckpointError, match="map_select"):
            env.save_checkpoint()
        assert env.observe() == state
        assert commands.read_bytes() == before
        for _ in range(20):
            if state["decision"] == "map_select":
                break
            state = env.step(interaction(state))
        default_map = env._engine.send({"cmd": "get_map"})
        assert env._engine.send({"cmd": "get_map", "include_start": False}) == default_map
        extended_map = env.get_map()
        assert "starting_point" not in default_map
        assert extended_map.pop("starting_point")["children"]
        assert extended_map == default_map
        yield env, env.save_checkpoint()


def room(env, choice):
    state = env.step(action("select_map_node", **coord(choice)))
    assert state["decision"] == "combat_play"
    assert env.get_map()["current_coord"] == coord(choice)
    for _ in range(300):
        if state["decision"] == "card_reward":
            assert not state.get("from_event")
            assert state["cards"] and "gold_earned" in state
            return state
        assert state["decision"] == "combat_play", state
        state = env.step(interaction(state))
    pytest.fail("Combat did not finish")


@requires_engine
def test_search_independent_aba_and_child(root, record_property):
    env, checkpoint = root
    original = checkpoint.path.read_bytes()
    choices = [choice for choice in env.observe()["choices"] if choice["type"] == "Monster"]
    assert len(choices) >= 2 and coord(choices[0]) != coord(choices[1])
    engines = []
    try:
        for label, choice in zip("AB", choices):
            with env.branch(checkpoint) as child:
                engines.append(child._engine.proc)
                assert child.observe() == env.observe()
                assert child.get_map() == env.get_map()
                reward = room(child, choice)
                position = child.position()
                assert len(position.prefix) >= 3
                record_property(f"branch_{label}", f"{coord(choice)}, {len(position.prefix) - 1} combat actions")
                if label == "A":
                    first = position
                    state = child.step(interaction(reward))
                    assert state["decision"] == "map_select"
                    card_id = reward["cards"][0]["id"]
                    assert sum(card["id"] == card_id for card in state["player"]["deck"]) == (
                        1 + sum(card["id"] == card_id for card in reward["player"]["deck"])
                    )
                    descendant = child.save_checkpoint()
                    descendant_bytes = descendant.path.read_bytes()
                    assert descendant.source == ("checkpoint", checkpoint.sha256)
                    with env.branch(descendant) as restored:
                        assert restored.observe() == state
                        assert restored.get_map() == child.get_map()
                    assert_unchanged(descendant, descendant_bytes)
            assert_unchanged(checkpoint, original)
        with env.replay(first) as repeated:
            engines.append(repeated._engine.proc)
            assert repeated.position() == first
        assert len({process.pid for process in engines}) == 3
        assert all(process.poll() == 0 for process in engines)
    finally:
        assert_unchanged(checkpoint, original)


@requires_engine
def test_search_rejects_corruption_and_divergence(root, tmp_path, monkeypatch):
    env, checkpoint = root
    original = checkpoint.path.read_bytes()
    bad_path = tmp_path / "tampered.save"
    bad_path.write_bytes(original + b" ")
    clients = []
    engine = search_env.EngineClient

    def track(**kwargs):
        client = engine(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(search_env, "EngineClient", track)
    try:
        for broken, message in (
            (replace(checkpoint, path=bad_path), "SHA-256"),
            (replace(checkpoint, observation_sha256="bad"), "SHA-256"),
            (replace(checkpoint, build=replace(checkpoint.build, adapter_version=-1)), "adapter"),
            (replace(checkpoint, runtime_version="9.0.0"), "runtime"),
        ):
            with pytest.raises(CheckpointError, match=message):
                env.branch(broken)
        assert len(clients) == 1 and clients[-1].proc.poll() is not None
        observation = json.loads(checkpoint.observation)
        observation["player"]["hp"] += 1
        encoded = json.dumps(observation).encode()
        with pytest.raises(ReplayMismatch, match=r"load decision.*player.hp"):
            env.branch(replace(checkpoint, observation=encoded,
                               observation_sha256=sha256(encoded).hexdigest()))

        assert len(clients) == 2 and clients[-1].proc.poll() is not None
        malformed = tmp_path / "malformed.save"
        malformed.write_bytes(b"{}")
        with pytest.raises(search_env.EngineFailure, match="load_save"):
            env.branch(replace(checkpoint, path=malformed, sha256=sha256(b"{}").hexdigest()))
        assert len(clients) == 3 and clients[-1].proc.poll() is not None

        choice = next(choice for choice in env.observe()["choices"] if choice["type"] == "Monster")
        with env.branch(checkpoint) as child:
            child.step(action("select_map_node", **coord(choice)))
            position = child.position()
        observed = json.loads(position.prefix[0].observation)
        del observed["player"]["hp"]
        step = replace(position.prefix[0], observation=json.dumps(observed).encode())
        with pytest.raises(ReplayMismatch, match=r"step 1 decision.*player.hp"):
            env.replay(replace(position, prefix=(step, *position.prefix)))
        assert clients[-1].proc.poll() is not None
        commands = (clients[-1].log_dir / "commands.jsonl").read_text().splitlines()
        assert [json.loads(line)["cmd"] for line in commands] == ["load_save", "get_map", "action"]

        world = json.loads(position.prefix[0].world_map)
        world["current_coord"]["col"] += 1
        step = replace(position.prefix[0], world_map=json.dumps(world).encode())
        with pytest.raises(ReplayMismatch, match=r"step 1 map.*current_coord.col"):
            env.replay(replace(position, prefix=(step, *position.prefix)))
        assert clients[-1].proc.poll() is not None
    finally:
        assert_unchanged(checkpoint, original)
