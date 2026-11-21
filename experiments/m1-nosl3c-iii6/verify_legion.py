"""Compare Legion of Bone with a missing or living Osty."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_root import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade, existing_osty):
    spec = dict(schema=3, act=1, act_variant="OVERGROWTH", character="Necrobinder",
                ascension=0, hp=75, max_hp=75, encounter="FLYCONID_NORMAL",
                seed="III6_LEGION", relics=[], potions=[],
                deck=[dict(id=card, upgrade=level) for card, level in
                      (("LEGION_OF_BONE", upgrade), ("BODYGUARD", 0), ("POKE", 0),
                       ("STRIKE_NECROBINDER", 0), ("DEFEND_NECROBINDER", 0))])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False,
                               rejected=[])["episode"]
        live = b["public_root"]
        def native_state():
            frame = native.request("i1_iib_native_stamp")
            return frame["state"][0]["exact_continuation_state"]

        def osty(raw):
            field, = [part for part in raw.split(";") if part.startswith("osty=")]
            return tuple(map(int, field.removeprefix("osty=").split("/")))

        initial = osty(native_state())
        assert initial[0] == 2**32 - 1 and initial[1:] == (0, 0), initial
        route = (["BODYGUARD"] if existing_osty else []) + ["LEGION_OF_BONE", "POKE"]
        for index, card in enumerate(route):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            if card is None:
                action, = [a for a in obs["actions"] if a["kind"] == "end_turn"]
            else:
                action, = [a for a in obs["actions"] if a["card"] is not None
                           and obs["hand"][a["card"]]["id"] == card and a["target"] in (None, 0)]
            before_hp = live["enemies"][0]["hp"]
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            assert episode["status"] == "active" and live["decision"] == "combat_play"
            raw = native_state()
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            fields = raw.split(";")
            powers = next(field for field in fields if field.startswith("P="))
            current = osty(raw)
            expected = 5 if card == "BODYGUARD" else (5 if existing_osty else 0) + 6 + 2 * upgrade
            assert current[0] != 2**32 - 1 and current[1:] == (expected, expected), current
            if frames:
                assert current[0] == frames[-1]["osty"][0]
            damage = before_hp - live["enemies"][0]["hp"]
            assert damage == (6 if card == "POKE" else 0), damage
            assert "DIE_FOR_YOU_POWER=1/" in powers, powers
            frames.append(dict(action=card, stamp=stamp, powers=powers, damage=damage, osty=current))
        iig.audit.compare_menu(targets.project(episode["observation"]), live,
                               target_indices(pred, native))
        pred.request("i1_n2_close")
    return dict(spec=spec, existing_osty=existing_osty, initial_osty=initial, frames=frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    shadow["save_json"](output / "legion.json", dict(engine=versions,
                       cases=[verify(output, versions, upgrade, applies) for upgrade, applies in ((0, False), (0, True), (1, False), (1, True))]))
