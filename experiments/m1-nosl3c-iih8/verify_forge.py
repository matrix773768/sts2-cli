"""Verify Furnace after Tyranny with a retained or exhausted Blade."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih7"))
from replay import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, exhaust_blade):
    spec = dict(schema=3, act=1, act_variant="UNDERDOCKS", character="Regent",
                ascension=0, hp=75, max_hp=75, encounter="TWO_TAILED_RATS_NORMAL",
                seed="IIH8_FORGE_ORDER", relics=[], potions=[],
                deck=[dict(id=card, upgrade=upgrade) for card, upgrade in
                      (("SPOILS_OF_BATTLE", 1), ("TYRANNY", 1), ("FURNACE", 1),
                       ("DEFEND_REGENT", 0), ("STRIKE_REGENT", 0))])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False,
                               rejected=[])["episode"]
        live = b["public_root"]
        selected = []
        card_to_exhaust = "SOVEREIGN_BLADE" if exhaust_blade else "DEFEND_REGENT"
        route = ("SPOILS_OF_BATTLE", "TYRANNY", "FURNACE", "end_turn",
                 "select_candidate", "confirm_selection")
        for index, planned in enumerate(route):
            obs = targets.project(episode["observation"])
            choice = obs["decision"]["phase"] == "choice"
            slots = {} if choice else target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            if planned == "select_candidate":
                candidate, = [i for i, card in enumerate(obs["decision"]["candidates"])
                              if card["id"] == card_to_exhaust]
                action, = [a for a in obs["actions"] if a["kind"] == planned and a["choice"] == candidate]
            elif planned in ("end_turn", "confirm_selection"):
                action, = [a for a in obs["actions"] if a["kind"] == planned]
            else:
                action, = [a for a in obs["actions"] if a["card"] is not None
                           and obs["hand"][a["card"]]["id"] == planned]
            live = native_step(native, action, slots, selected) or live
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            assert episode["status"] == "active"
            if live["decision"] == "combat_play":
                frame = native.request("i1_iib_native_stamp")
                raw = frame["state"][0]["exact_continuation_state"]
                stamp = sha256(raw.encode()).hexdigest()
                assert stamp == episode["audit_stamp"], targets.field_diff(
                    pred.request("i1_iid_prediction_text")["text"], raw)
                blades = [field for field in raw.split(";") if "SOVEREIGN_BLADE" in field]
                frames.append(dict(action=planned, stamp=stamp, blade_fields=blades))
        iig.audit.compare_menu(targets.project(episode["observation"]), live,
                               target_indices(pred, native))
        initial = frames[0]["blade_fields"]
        final = frames[-1]["blade_fields"]
        assert len(initial) == 1 and initial[0].startswith("H=")
        hand, = [field for field in final if field.startswith("H=")]
        assert hand.count("SOVEREIGN_BLADE") == 1
        assert len(final) == (2 if exhaust_blade else 1), final
        pred.request("i1_n2_close")
    return dict(spec=spec, exhausted=card_to_exhaust, frames=frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    cases = [verify(output, versions, exhaust) for exhaust in (True, False)]
    shadow["save_json"](output / "forge.json", dict(engine=versions, cases=cases))
