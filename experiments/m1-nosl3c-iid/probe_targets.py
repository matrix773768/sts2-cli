"""Audit the native team-effect action and an unselectable solo ally action."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from targets import CAPTURE, open_worker, project, worker_bind
from qualify_native import native_action
from nosl_experience import save_json


def run(output, solver):
    versions = worker_bind(output, solver)
    base = json.loads((Path(__file__).parent.parent / "m1-nosl3c-iib/integration.json").read_bytes())["batches"][0][0]
    results = []
    for role, card in (("Defect", "ENERGY_SURGE"), ("Regent", "LARGESSE")):
        spec = base | dict(character=role,
                           deck=[dict(id=c, upgrade=0) for c in (card,) + ("STRIKE_" + role.upper(),) * 4])
        with ExitStack() as stack:
            pred, native = [open_worker(output, stack, versions) for _ in range(2)]
            left, _ = CAPTURE(pred, spec)
            right, _ = CAPTURE(native, spec)
            assert left["native"] == right["native"]
            native.teacher_frames, native.teacher_choices = [], []
            native.request("i1_begin")
            state = pred.request("i1_n2_reset", arm="A", cap=8, potions=False, rejected=[])["episode"]
            obs = project(state["observation"])
            slot = next(c["index"] for c in obs["hand"] if c["id"] == card)
            native_card = right["public_root"]["hand"][slot]
            moves = [a for a in obs["actions"] if a["card"] == slot]
            result = dict(card=card, target_type=native_card["target_type"], moves=len(moves))
            if native_card["target_type"] == "AnyAlly":
                assert not moves and native_card["legal_target_indices"] == []
            else:
                action, = moves
                assert action["target"] is None and action["target_type"] == "AllAllies"
                after = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
                live = native_action(native, "play_card", card_index=slot)
                frame = native.request("i1_iib_native_stamp")["state"][0]
                stamp = sha256(frame["exact_continuation_state"].encode()).hexdigest()
                assert after["audit_stamp"] == stamp and after["status"] == "active"
                assert after["observation"]["energy"] == live["energy"]
                result.update(exact_match=True, energy_before=obs["energy"], energy_after=live["energy"])
            pred.request("i1_n2_close")
            results.append(result)
    save_json(output / "targets.json", dict(versions=versions, results=results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args.output.resolve(), args.solver.resolve())
