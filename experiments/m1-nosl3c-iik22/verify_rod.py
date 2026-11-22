"""Compare native Lightning Rod after lethal and nonlethal full-queue channels."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import re
import sys
from time import perf_counter

from verify_route import tools
from probe_prefix import native_step, target_indices


def rod_layers(raw):
    match = re.search(r":LIGHTNING_ROD_POWER=(\d+)/", raw)
    return int(match[1]) if match else 0


def check(output, versions, lethal):
    targets = tools["targets"]
    spec = tools["batch"]("iij5b-serial-holdout", 1, "000010")["spec"]
    spec = spec | {"deck": ([{"id": "ZAP", "upgrade": 1}] * 3
                           + [{"id": "LIGHTNING_ROD", "upgrade": 1},
                              {"id": "DEFEND_DEFECT", "upgrade": 0}])}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=40, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        frames = []
        applied = None
        while state["status"] == "active":
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            tools["compare_menu"](obs, live, slots)
            enemy, = live["enemies"]
            effective_hp = enemy["hp"] + enemy["block"]
            card = "ZAP" if len(frames) < 3 else (
                "LIGHTNING_ROD" if applied is None and (not lethal or 9 < effective_hp <= 17)
                else None)
            menu = obs["actions"]
            plays = [a for a in menu if a["card"] is not None
                     and obs["hand"][a["card"]]["id"] == card]
            if card is not None:
                assert plays, (card, obs["hand"], effective_hp)
            action = plays[0] if plays else next(a for a in menu if a["kind"] == "end_turn")
            live = native_step(native, action, slots, [])
            state = pred.request("i1_n2_step", position=state["actions"],
                                 index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            differences = {} if stamp == state["audit_stamp"] else targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            orbs = next(field for field in raw.split(";") if field.startswith("O="))
            layers = rod_layers(raw)
            if card == "LIGHTNING_ROD":
                assert layers >= 2 and orbs.count("LIGHTNING_ORB") == 3, raw
                applied = layers
            frames.append(dict(action=card or "end_turn", hp_before=enemy["hp"],
                               block_before=enemy["block"], decision=live["decision"],
                               layers=layers, orbs=orbs, stamp=stamp, differences=differences))
            if differences or live["decision"] == "card_reward" or (applied and card is None):
                break
        pred.request("i1_n2_close")
    final = frames[-1]
    assert applied and final["action"] == "end_turn", frames[-2:]
    assert final["decision"] == ("card_reward" if lethal else "combat_play"), final
    assert final["layers"] == applied - (0 if lethal else 1), final
    return frames


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    for name, lethal in (("nonlethal", False), ("lethal", True)):
        start = perf_counter()
        frames = check(output, versions, lethal)
        duration = perf_counter() - start
        tools["save_json"](output / f"{name}.json", dict(engine=versions, frames=frames, seconds=duration))
        print(name, duration, len(frames), frames[-1], flush=True)
