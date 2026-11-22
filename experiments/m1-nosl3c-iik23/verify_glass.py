"""Compare Glass Orb decay on live and terminal native turn boundaries."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import re
import sys
from time import perf_counter

from verify_route import tools
from probe_prefix import native_step, target_indices


def check(output, versions):
    targets = tools["targets"]
    spec = tools["batch"]("iij5b-serial-holdout", 1, "000021")["spec"]
    spec = spec | {"deck": ([{"id": "GLASSWORK", "upgrade": 0}] * 3
                           + [{"id": "DEFEND_DEFECT", "upgrade": 0}] * 2)}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=18, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        frames = []
        while state["status"] == "active":
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            tools["compare_menu"](obs, live, slots)
            plays = [a for a in obs["actions"] if a["card"] is not None
                     and obs["hand"][a["card"]]["id"] == "GLASSWORK"]
            action = plays[0] if obs["turn"] <= 2 and plays else next(
                a for a in obs["actions"] if a["kind"] == "end_turn")
            hp = [(e["hp"], e["block"]) for e in live["enemies"]]
            live = native_step(native, action, slots, [])
            state = pred.request("i1_n2_step", position=state["actions"],
                                 index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            differences = {} if stamp == state["audit_stamp"] else targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            values = [int(n) for n in re.findall(r"GLASS_ORB\[(\d+)/", raw)]
            frames.append(dict(action=action["kind"], turn=obs["turn"], hp_before=hp,
                               decision=live["decision"], values=values, stamp=stamp,
                               differences=differences))
            if differences or live["decision"] == "card_reward":
                break
        pred.request("i1_n2_close")
    return frames


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    start = perf_counter()
    frames = check(output, versions)
    duration = perf_counter() - start
    tools["save_json"](output / "fixture.json", dict(engine=versions, frames=frames, seconds=duration))
    for frame in frames:
        if frame["action"] == "end_turn" or frame["differences"]:
            print(frame)
    print(duration, len(frames))
    assert frames[-1]["decision"] == "card_reward" and frames[-1]["action"] == "end_turn"
    assert any(f["action"] == "end_turn" and f["decision"] == "combat_play"
               and not f["differences"] for f in frames)
