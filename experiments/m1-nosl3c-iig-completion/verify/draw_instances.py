"""Prove that equal-looking public candidates can bind to different draw instances."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import bind, targets
from probe_prefix import native_step, target_indices
from nosl_experience import save_json
from qualify_native import compare_menu, qualify
from training import Policy


BASE = dict(schema=1, act=1, character="Necrobinder", ascension=0, hp=80, max_hp=80,
            encounter="SHRINKER_BEETLE_WEAK", relics=[], potions=[])
CARDS = [("CLEANSE", 0)] * 3 + [("STRIKE_NECROBINDER", 0)] * 5 + [
    ("DEFEND_NECROBINDER", 0), ("DEFEND_NECROBINDER", 0),
    ("STRIKE_NECROBINDER", 1), ("DEFEND_NECROBINDER", 1)]


def open_selector(pred, native, spec):
    first, _ = targets.CAPTURE(pred, spec)
    second, _ = targets.CAPTURE(native, spec)
    assert first["native"] == second["native"]
    native.teacher_frames, native.teacher_choices = [], []
    native.request("i1_begin")
    initial = pred.request("i1_n2_reset", arm="A", cap=128, potions=False, rejected=[])["episode"]
    obs = targets.project(initial["observation"])
    action = next((a for a in obs["actions"] if a["card"] is not None
                   and obs["hand"][a["card"]]["id"] == "CLEANSE"), None)
    if action is None:
        return None
    live = native_step(native, action, target_indices(pred, native), [])
    state = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
    assert state["status"] == "active"
    public = targets.project(state["observation"])
    compare_menu(public, live)
    assert public["decision"]["effect"] == "Exhaust"
    assert len(public["decision"]["candidates"]) == public["draw_count"]
    return public


def choose(pred, native, public, index):
    select = next(a for a in public["actions"] if a["choice"] == index)
    selected = pred.request("i1_n2_step", position=1, index=select["index"])["episode"]
    commit = next(a for a in targets.project(selected["observation"])["actions"]
                  if a["kind"] == "confirm_selection")
    native_step(native, commit, {}, [index])
    state = pred.request("i1_n2_step", position=2, index=commit["index"])["episode"]
    native_frame = native.request("i1_iib_native_stamp")["state"][0]
    raw = native_frame["exact_continuation_state"]
    assert state["status"] == "active"
    assert state["audit_stamp"] == sha256(raw.encode()).hexdigest()
    pred.request("i1_n2_close")
    return native_frame


def verify(output, solver):
    targets.configure()
    versions = bind(output, solver)
    torch.manual_seed(11)
    actor = Policy().eval()
    for seed in range(12):
        spec = BASE | {"seed": f"IIGDRAW{seed}",
                       "deck": [{"id": card, "upgrade": upgrade} for card, upgrade in CARDS]}
        with ExitStack() as stack:
            pairs = [[targets.open_worker(output, stack, versions) for _ in range(2)] for _ in range(2)]
            public = [open_selector(*pair, spec) for pair in pairs]
            assert public[0] == public[1]
            if public[0] is None:
                continue
            choice = public[0]["decision"]
            instances = defaultdict(list)
            for card in choice["candidates"]:
                instances[card["id"], card["upgrade"]].append(card["index"])
            pair = next((values for values in instances.values() if len(values) > 1), ())
            if not pair:
                continue
            indices = [pair[0], pair[-1]]
            probabilities, *_ = actor(targets.Decision(public[0]), torch.zeros(actor.history.hidden_size))
            assert torch.isfinite(probabilities).all()
            assert torch.isclose(probabilities.softmax(0).sum(), torch.tensor(1.0))
            left, right = [choose(*workers, obs, index)
                           for workers, obs, index in zip(pairs, public, indices, strict=True)]
            difference = targets.field_diff(left["exact_continuation_state"], right["exact_continuation_state"])
            if "D" in difference:
                win = qualify(output, versions, spec, "STRIKE_NECROBINDER", opening=("CLEANSE",))
                assert win["terminal"] == "predicted_win" and win["native_terminal"], win
                save_json(output / "draw-instances.json", dict(engine=versions, spec=spec, indices=indices,
                    public=choice, exact_matches=2, full_victory=win, draw_after_first=difference["D"]["prediction"],
                    draw_after_last=difference["D"]["native"]))
                return
    raise AssertionError("No repeated-instance test produced different draw order")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        verify(output, args.solver.resolve())
