"""Exercise nonlethal and lethal end-of-turn Lightning passives in native combat."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

from verify_routes import tools
from probe_prefix import native_step, target_indices


def check(output, versions):
    targets = tools["targets"]
    spec = tools["batch"]("iij5b-serial-holdout", 1, "000010")["spec"]
    spec = spec | {"deck": ([{"id": "ZAP", "upgrade": 1}] * 3
                           + [{"id": "DEFEND_DEFECT", "upgrade": 0}] * 2)}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=32, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        frames = []
        while state["status"] == "active":
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            tools["compare_menu"](obs, live, slots)
            enemy, = live["enemies"]
            closing = enemy["hp"] <= 9
            card = "ZAP" if len(frames) < 3 else "DEFEND_DEFECT" if closing else None
            menu = obs["actions"]
            plays = [a for a in menu if a["card"] is not None
                     and obs["hand"][a["card"]]["id"] == card]
            if len(frames) < 3:
                assert plays, obs["hand"]
            action = plays[0] if plays else next(a for a in menu if a["kind"] == "end_turn")
            live = native_step(native, action, slots, [])
            state = pred.request("i1_n2_step", position=state["actions"],
                                 index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            differences = {} if stamp == state["audit_stamp"] else targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
            frames.append(dict(action=card if plays else "end_turn", hp_before=enemy["hp"],
                               decision=live["decision"], terminal=frame["terminal"],
                               history=fields["Y"], attacks=fields["AttackStarts"],
                               stamp=stamp, differences=differences))
            if differences or live["decision"] == "card_reward":
                break
        pred.request("i1_n2_close")
    assert frames[-1]["decision"] == "card_reward" and frames[-1]["history"] == "0/0/2/2", frames[-1]
    assert any(f["action"] == "end_turn" and f["decision"] == "combat_play" for f in frames)
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
    print(duration, len(frames), frames[-1])
