"""Verify Hibernate casts and clears across independent native turns."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_root import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade):
    spec = dict(schema=3, act=1, act_variant="UNDERDOCKS", character="Defect",
                ascension=0, hp=75, max_hp=75, encounter="SLUDGE_SPINNER_WEAK",
                seed="III2_HIBERNATE", relics=[], potions=[],
                deck=[dict(id=card, upgrade=level) for card, level in
                      (("HIBERNATE", upgrade), ("COOLHEADED", 0), ("DEFEND_DEFECT", 0),
                       ("DEFEND_DEFECT", 0), ("DEFEND_DEFECT", 0))])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=6, potions=False,
                               rejected=[])["episode"]
        live = b["public_root"]
        for index, card in enumerate(("COOLHEADED", "HIBERNATE", None, None)):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            if card is None:
                action, = [a for a in obs["actions"] if a["kind"] == "end_turn"]
            else:
                action, = [a for a in obs["actions"] if a["card"] is not None
                           and obs["hand"][a["card"]]["id"] == card]
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            assert episode["status"] == "active" and live["decision"] == "combat_play"
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            fields = raw.split(";")
            powers = next(field for field in fields if field.startswith("P="))
            orbs = next(field for field in fields if field.startswith("O="))
            assert ("HIBERNATE_POWER=1/" in powers) == (index == 1), powers
            assert orbs.count("FROST_ORB") == (1 if index == 0 else 3), orbs
            frames.append(dict(action=card or "end_turn", stamp=stamp, powers=powers, orbs=orbs,
                               hp=live["player"]["hp"], block=live["player"]["block"]))
        iig.audit.compare_menu(targets.project(episode["observation"]), live,
                               target_indices(pred, native))
        pred.request("i1_n2_close")
    return dict(spec=spec, frames=frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    shadow["save_json"](output / "hibernate.json", dict(engine=versions,
                       cases=[verify(output, versions, upgrade) for upgrade in (0, 1)]))
