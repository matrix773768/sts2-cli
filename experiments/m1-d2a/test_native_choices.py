"""Native regression using the two D1 histories and their legal map saves."""
import os
from pathlib import Path
import sys
from threading import Event
from time import monotonic

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-d1"))
import bank

BASE_HOST = "m1-f3b-build"
FIXED_HOST = "m1-d2a-build"
CASES = {
    "silent-3": ("NEOWS_FURY", 7, 6, (0, 2), [8, 0]),
    "iron-4": ("ARMAMENTS", 8, 5, (1, 1), [1]),
}
STEP_FIELDS = ("action", "choice_requests", "choice_checks")


@pytest.fixture(scope="module")
def banks():
    root = HERE.parents[1]
    source = Path(os.environ.get("STS2_D2A_BASELINE", root / "logs/m1-d1-v1-w2")).resolve()
    reruns = Path(os.environ.get("STS2_D2A_RERUNS", root / "logs/m1-d2a/reruns")).resolve()
    return source, bank.read(source / "manifest.json"), bank.read(reruns / "manifest.json")


def run_for(manifest, name):
    return next(r for r in manifest["runs"] if r["id"] == name)


def resolved(row):
    return {k: row[k] for k in STEP_FIELDS}


def test_two_bank_reruns(banks):
    _, original, reruns = banks
    assert {r["id"] for r in reruns["runs"]} == CASES.keys()
    terminal_floors = {"silent-3": 7, "iron-4": 12}
    new_roots = []
    for name in CASES:
        old, new = (run_for(m, name) for m in (original, reruns))
        assert all(old[k] == new[k] for k in ("history", "partition", "spec", "offline_teacher_assisted"))
        assert new["status"] == "death" and not new["offline_teacher_assisted"]
        assert new["last_context"]["floor"] == terminal_floors[name]
        common = len(old["commands"]) - 1
        assert old["commands"][:common] == new["commands"][:common]
        assert new["commands"][common]["resolved"]["action"] == old["commands"][common]["resolved"]["action"]
        assert len(new["commands"]) > len(old["commands"])
        before, after = ([r for r in m["roots"] if r["run_id"] == name] for m in (original, reruns))
        for expected, actual in zip(before, after, strict=False):
            for field in ("identity", "public_root", "map_public_sha256", "map_edges_sha256", "entry"):
                assert expected[field] == actual[field]
        assert len(before) <= len(after)
        new_roots.extend(after[len(before):])
    assert [(r["run_id"], r["context"]["floor"], r["identity"]["encounter"]) for r in new_roots] == [
        ("iron-4", 12, "BYGONE_EFFIGY_ELITE")]
    assert len(reruns["roots"]) == len(reruns["validations"]) == 10
    assert all(v["status"] == "pass" for v in reruns["validations"])


def replay_prefix(host, log, commands):
    bank.setup(log, host)
    frames = []
    with bank.Session(log, monotonic() + 35, Event()) as game:
        for command in commands:
            if command["cmd"] == "f1_step":
                row = game.request("f1_step", step=command["step"], audit=True)
                assert not row["choice_failure"]
                assert resolved(row) == command["resolved"]
                state = row["decision"]
                frames.append((state, row["pre_audit"], row["post_audit"]))
            else:
                state = game.request(**command)
                native = (game.request("f1_begin") if command.get("action") == "select_map_node"
                          and state["decision"] == "combat_play" else None)
                world = bank.boundaries(game, state) if state["decision"] == "map_select" else None
                frames.append((state, native, world))
    return frames


@pytest.mark.parametrize("name", CASES)
def test_natural_history_prefix(banks, tmp_path, name):
    _, original, _ = banks
    prefix = run_for(original, name)["commands"][:-1]
    expected = replay_prefix(BASE_HOST, tmp_path, prefix)
    actual = replay_prefix(FIXED_HOST, tmp_path, prefix)
    assert len(expected) == len(actual)
    for index, (a, b) in enumerate(zip(expected, actual), 1):
        assert a == b, (name, index)
    print(name, "equal public/native/RNG prefix commands", len(prefix))


def replay_fixture(source, root, actions, host, log, manual_indexes=None):
    bank.setup(log, host)
    with bank.restore(source, root, monotonic() + 20, Event()) as (game, _):
        for command in actions[:-1]:
            row = game.request("f1_step", step=command["step"], audit=True)
            assert not row["choice_failure"] and resolved(row) == command["resolved"]
        last = actions[-1]
        if manual_indexes is None:
            return game.request("f1_step", step=last["step"], audit=True)
        pre = game.request("f1_audit")
        prompt = game.execute_action(last["resolved"]["action"])
        assert prompt["decision"] == "card_select"
        state = game.execute_action(dict(action="select_cards",
                                   args={"indices": ",".join(str(i) for i in manual_indexes)}))
        assert state["decision"] == "combat_play"
        return prompt, state, pre, game.request("f1_audit")


@pytest.mark.parametrize("name", CASES)
def test_native_choice_instance(banks, tmp_path, name):
    source, original, _ = banks
    card, floor, step, limits, indexes = CASES[name]
    root = next(r for r in original["roots"] if r["run_id"] == name and r["context"]["floor"] == floor)
    actions = run_for(original, name)["commands"][root["entry_command_index"]:]
    assert len(actions) == step
    old = replay_fixture(source, root, actions, BASE_HOST, tmp_path)
    fixed = replay_fixture(source, root, actions, FIXED_HOST, tmp_path)
    assert old["choice_failure"] == "unknown_or_repeated_request"
    assert old["decision"]["type"] == "error"
    assert old["choice_requests"] == actions[-1]["resolved"]["choice_requests"]
    assert not fixed["choice_failure"] and fixed["action"] == old["action"]
    assert fixed["pre_audit"] == old["pre_audit"]
    request, = fixed["choice_requests"]
    assert request["action"] == card and request["indexes"] == indexes
    assert (request["min_select"], request["max_select"]) == limits
    check = fixed["choice_checks"][0]
    assert check["sampling_choice"] and check["rng_at_choice"] == check["rng_after"]
    assert [c["option"] for c in check["instances"]] == indexes
    assert all(c["hand_index"] >= 0 and c["absent_from_discard"] for c in check["instances"])
    for c in check["instances"]:
        assert c["upgrade_after"] - c["upgrade_before"] == (1 if card == "ARMAMENTS" else 0)
    prompt, manual, pre, post = replay_fixture(source, root, actions, BASE_HOST, tmp_path, indexes)
    assert (prompt["min_select"], prompt["max_select"]) == limits
    assert [(c["index"], c["id"]) for c in prompt["cards"]] == [
        (c["index"], "CARD." + c["id"]) for c in request["candidates"]]
    assert fixed["pre_audit"] == {k: pre[k] for k in ("stamp", "rng")}
    assert fixed["post_audit"] == {k: post[k] for k in ("stamp", "rng")}
    assert fixed["decision"] == manual
    print(name, card, "matches external native selection", fixed["post_audit"])
