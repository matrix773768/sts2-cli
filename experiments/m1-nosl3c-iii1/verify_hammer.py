"""Compare normal and upgraded Hammer Time against independent native combat."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_roots import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade):
    spec = dict(schema=3, act=1, act_variant="UNDERDOCKS", character="Regent",
                ascension=0, hp=75, max_hp=75, encounter="TWO_TAILED_RATS_NORMAL",
                seed="III1_HAMMER_FORGE", relics=[], potions=[],
                deck=[dict(id=card, upgrade=level) for card, level in
                      (("HAMMER_TIME", upgrade), ("SPOILS_OF_BATTLE", 1),
                       ("DEFEND_REGENT", 0), ("STRIKE_REGENT", 0), ("DEFEND_REGENT", 0))])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=4, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        for i, card in enumerate(("HAMMER_TIME", "SPOILS_OF_BATTLE")):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            action, = [a for a in obs["actions"] if a["card"] is not None
                       and obs["hand"][a["card"]]["id"] == card]
            if i == 0:
                assert action["cost"] == 2 - upgrade
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=i, index=action["index"])["episode"]
            assert episode["status"] == "active" and live["decision"] == "combat_play"
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            powers = next(field for field in raw.split(";") if field.startswith("P="))
            blades = [field for field in raw.split(";") if "SOVEREIGN_BLADE" in field]
            assert "HAMMER_TIME_POWER=1/" in powers
            assert len(blades) == i
            if i == 1:
                assert blades[0].startswith("H=") and "Damage=19," in blades[0]
                assert blades[0].count("SOVEREIGN_BLADE") == 1
            frames.append(dict(card=card, cost=action["cost"], powers=powers,
                               blades=blades, stamp=stamp))
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
    shadow["save_json"](output / "hammer.json", dict(engine=versions,
                       cases=[verify(output, versions, u) for u in (0, 1)]))
