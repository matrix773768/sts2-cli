"""Compare native Suck after the same lethal and nonlethal Fossil Stalker attack."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import re
import sys
from time import perf_counter

from verify_route import LEDGER, ROOT, STEP, tools
from probe_prefix import native_step, target_indices


def strength(raw):
    match = re.search(r":STRENGTH_POWER=(\d+)/", raw)
    return int(match[1]) if match else 0


def check(output, versions, lethal):
    targets = tools["targets"]
    spec = tools["batch"](LEDGER, STEP, ROOT)["spec"]
    spec = spec | {"hp": 1 if lethal else spec["max_hp"],
                   "deck": [{"id": "DEFEND_NECROBINDER", "upgrade": 0}] * 5}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=4, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        obs = targets.project(state["observation"])
        slots = target_indices(pred, native)
        tools["compare_menu"](obs, live, slots)
        enemy, = live["enemies"]
        assert enemy["intends_attack"], enemy
        before = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
        suck = int(re.search(r":SUCK_POWER=(\d+)/", before)[1])
        action, = [a for a in obs["actions"] if a["kind"] == "end_turn"]
        after = native_step(native, action, slots, [])
        state = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
        frame = native.request("i1_iib_native_stamp")
        raw = frame["state"][0]["exact_continuation_state"]
        stamp = sha256(raw.encode()).hexdigest()
        differences = {} if stamp == state["audit_stamp"] else targets.field_diff(
            pred.request("i1_iid_prediction_text")["text"], raw)
        pred.request("i1_n2_close")
    assert suck > 0 and after["decision"] == ("game_over" if lethal else "combat_play")
    assert strength(raw) == strength(before) + (0 if lethal else suck)
    return dict(hp=spec["hp"], attack=enemy["intents"], suck=suck, decision=after["decision"],
                strength_before=strength(before), strength_after=strength(raw),
                stamp=stamp, differences=differences)


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    for name, lethal in (("nonlethal", False), ("lethal", True)):
        start = perf_counter()
        result = check(output, versions, lethal)
        duration = perf_counter() - start
        tools["save_json"](output / f"{name}.json", dict(engine=versions, result=result, seconds=duration))
        print(name, duration, result, flush=True)
