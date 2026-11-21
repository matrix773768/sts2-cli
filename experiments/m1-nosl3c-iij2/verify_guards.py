"""Independently replay Guards prefixes and compare confirmation outcomes."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
TOOLS = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
targets = TOOLS["targets"]
from probe_prefix import native_step, target_indices
from replay_frozen import key
from qualify_native import native_action


def verify(output, versions, step, root, boundary, selection):
    saved = TOOLS["batch"]("iii9b-holdout", step, root)
    route = saved["rows"][0]["transitions"][:boundary]
    compare = TOOLS["compare_menu"]
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        first, _ = targets.CAPTURE(pred, saved["spec"])
        second, _ = targets.CAPTURE(native, saved["spec"])
        assert first["native"] == second["native"]
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=32, potions=False, rejected=[])["episode"]
        live = second["public_root"]
        stamps = []
        for position, fixed in enumerate(route):
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            compare(obs, live, slots)
            assert all(obs[name] == value for name, value in fixed["observation"].items()
                       if name != "actions")
            action, = [a for a in obs["actions"] if key(a) == key(fixed["action"])]
            live = native_step(native, action, slots, [])
            state = pred.request("i1_n2_step", position=position, index=action["index"])["episode"]
            assert state["status"] == "active", state
            if live["decision"] != "card_select":
                stamps.append(compare_state(pred, native, state))
        obs = targets.project(state["observation"])
        compare(obs, live, {})
        choice = obs["decision"]
        assert choice["effect"] == "Transform"
        result = dict(root=f"{step}:{root}", boundary=boundary, prefix_stamps=stamps,
                      choice=choice, native_min=live["min_select"], native_max=live["max_select"],
                      legal_actions=obs["actions"])
        if selection is None:
            return result

        invalid = pred.request("i1_n2_step", position=boundary, index=len(obs["actions"]))["episode"]
        assert invalid["status"] == "invalid_action"
        indices = [card["index"] for card in choice["candidates"]][:selection]
        for position, index in enumerate(indices, boundary):
            action, = [a for a in obs["actions"] if a["choice"] == index]
            state = pred.request("i1_n2_step", position=position, index=action["index"])["episode"]
            obs = targets.project(state["observation"])
        assert obs["decision"]["selected"] == indices
        confirm, = [a for a in obs["actions"] if a["kind"] == "confirm_selection"]
        live = native_action(native, "select_cards", indices=",".join(map(str, indices)))
        state = pred.request("i1_n2_step", position=boundary + len(indices),
                             index=confirm["index"])["episode"]
        assert state["status"] == "active", state
        stamp = compare_state(pred, native, state)
        after = targets.project(state["observation"])
        compare(after, live, target_indices(pred, native))
        return result | dict(selected=indices, invalid=invalid["status"], stamp=stamp, after=after)


def compare_state(pred, native, state):
    raw = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
    stamp = sha256(raw.encode()).hexdigest()
    assert stamp == state["audit_stamp"], targets.field_diff(
        pred.request("i1_iid_prediction_text")["text"], raw)
    return stamp


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    targets.configure()
    versions = TOOLS["bind"](output, solver)
    cases = [verify(output, versions, step, root, boundary, selection)
             for step, root, boundary, selection in (
                 (0, "000020", 2, None), (1, "000005", 4, None),
                 (0, "000020", 2, 0), (0, "000020", 2, 1), (0, "000020", 2, 3))]
    TOOLS["save_json"](output / "guards.json", dict(engine=versions, cases=cases))
