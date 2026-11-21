"""Fork the fixed route at the threshold and compare lethal and live outcomes."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

from verify_route import TOOLS
from probe_prefix import native_step, target_indices
from replay_frozen import key

targets = TOOLS["targets"]
POWER = "DRAW_CARDS_NEXT_TURN_POWER"


def verify(output, versions, lethal):
    saved = TOOLS["batch"]("iii9a-sample-1", 0, "000000")
    route = saved["rows"][0]["transitions"]
    compare = TOOLS["compare_menu"]
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        first, _ = targets.CAPTURE(pred, saved["spec"])
        second, _ = targets.CAPTURE(native, saved["spec"])
        assert first["native"] == second["native"]
        native.request("i1_begin")
        live = second["public_root"]
        state = pred.request("i1_n2_reset", arm="A", cap=64, potions=False, rejected=[])["episode"]
        selected = []
        frames = []
        tail = ["GLIMMER", "select_candidate", "confirm_selection", "end_turn"]
        for position in range(43 if lethal else 42 + len(tail)):
            obs = targets.project(state["observation"])
            slots = {} if obs["decision"]["phase"] == "choice" else target_indices(pred, native)
            compare(obs, live, slots)
            if position < 42 or lethal:
                action, = [a for a in obs["actions"] if key(a) == key(route[position]["action"])]
            else:
                step = tail[position - 42]
                action = next(a for a in obs["actions"] if a["kind"] == step or
                              (a["card"] is not None and obs["hand"][a["card"]]["id"] == step))
            live = native_step(native, action, slots, selected) or live
            state = pred.request("i1_n2_step", position=position, index=action["index"])["episode"]
            if live["decision"] == "card_select":
                continue
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == state["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            if position >= 41:
                powers = next(f for f in raw.split(";") if f.startswith("P="))
                frames.append(dict(position=position, power=POWER in powers, powers=powers,
                                   terminal=frame["terminal"], stamp=stamp, native_state=raw))
        if lethal:
            assert [f["power"] for f in frames] == [False, False] and frames[-1]["terminal"]
        else:
            assert [f["power"] for f in frames] == [False, True, False]
            compare(targets.project(state["observation"]), live, target_indices(pred, native))
        return dict(lethal=lethal, frames=frames)


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    targets.configure()
    versions = TOOLS["bind"](output, solver)
    cases = [verify(output, versions, lethal) for lethal in (True, False)]
    TOOLS["save_json"](output / "power.json", dict(engine=versions, cases=cases))
