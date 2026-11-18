"""Verify the synthetic spike artifacts and exercise the host isolation boundary."""
import os
from pathlib import Path

import run as synth

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("STS2_S1_RESULTS", HERE.parents[1] / "logs/m1-s1/final"))


def test_independent_root_and_seed_deck_deltas():
    result = synth.bank.read(WORK / "results.json")
    variants = result["variants"]
    base, seed, upgrade = (variants[name]["root"] for name in ("base", "seed", "upgrade"))
    assert all(v["root"]["synthetic"] and v["root"]["native_verified"]
               and not v["root"]["native_reachable"] for v in variants.values())
    assert all(len(v["audit"]["rebuilds"]) == 2 for v in variants.values())
    assert len({v["root"]["identity"]["live"] for v in variants.values()}) == 3
    assert base["native"]["run_rng"]["rngs"] != seed["native"]["run_rng"]["rngs"]
    assert base["native"]["player_rng"]["rngs"] != seed["native"]["player_rng"]["rngs"]
    for root in (base, seed, upgrade):
        assert all(set(stream) == {"counter", "s0", "s1", "s2", "s3"}
                   for key in ("run_rng", "player_rng") for stream in root["native"][key]["rngs"].values())
        assert root["native"]["visited_map_nodes"] == 0
        assert len(root["native"]["hand"]) == len(root["native"]["draw"]) == 5
    assert base["native"]["deck"][:-1] == upgrade["native"]["deck"][:-1]
    assert base["native"]["deck"][-1] == {"id": "BASH", "upgrade": 0}
    assert upgrade["native"]["deck"][-1] == {"id": "BASH", "upgrade": 1}
    assert len(variants["base"]["audit"]["legal_action_frames"]) == 3
    assert result["native_save_or_replay_files"] == 0


def test_verified_f3b_route():
    result = synth.bank.read(WORK / "results.json")
    search = result["f3b"]
    assert search["uses_hidden_rng"] and search["cap"] == 128 and not search["potions"]
    assert search["status"] == "win" and search["transitions"] == 13
    native = search["native_replay"]
    assert native["strict_terminal"] and native["matched_actions"] == len(search["actions"]) == 13
    assert all(frame["expected_sha256"] == frame["actual_sha256"] for frame in native["trace"])
    assert native["native_final"]["outcome"]["final_enemy_hp"] == 0
    assert result["variants"]["base"]["root"]["level"] == "L3"


def test_isolated_host_rejects_map_io_and_applies_nondefault_max_hp(tmp_path):
    cases = synth.bank.read(HERE / "cases.json")
    spec = cases["base"] | {"max_hp": 85, "relics": []}
    path = tmp_path / "forbidden.save"
    synth.bank.versions_for_host(tmp_path, synth.HOST)
    with synth.new_session(tmp_path) as game:
        surfaces, _ = synth.capture(game, spec)
        assert surfaces["identity"]["resources"]["max_hp"] == 85
        assert surfaces["identity"]["resources"]["relics"] == []
        for cmd in ({"cmd": "write_continue_save", "path": str(path)},
                    {"cmd": "load_save", "path": str(path)},
                    {"cmd": "quit", "path": str(path)},
                    {"cmd": "get_map"},
                    {"cmd": "synthetic_start", "spec": spec}):
            assert game.engine.send(cmd)["type"] == "error"
        assert not path.exists()
        assert game.request("f1_audit")["stamp"] == surfaces["identity"]["live"]
