"""Compare native and predicted Free Attack through grant, use, and owner death."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import runpy

shadow = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            "m1-nosl3c-iih4/verify_shadow.py"))
bind, iig, targets = (shadow[name] for name in ("bind", "iig", "targets"))
native_step, target_indices = (shadow[name] for name in ("native_step", "target_indices"))


def verify(output, versions, encounter, act_variant, actions, expected):
    spec = dict(schema=3, act=1, act_variant=act_variant, character="Ironclad",
                ascension=0, hp=1, max_hp=80, encounter=encounter,
                seed="IIH6_FREE_ATTACK", relics=[], potions=[],
                deck=[dict(id=card, upgrade=0) for card in
                      ("UNRELENTING", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD",
                       "DEFEND_IRONCLAD", "DEFEND_IRONCLAD")])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False,
                               rejected=[])["episode"]
        menu = b["public_root"]
        for index, (card, (free_attack, illusion)) in enumerate(zip(actions, expected, strict=True)):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, menu, slots)
            if card:
                action = next(action for action in obs["actions"]
                              if action["card"] is not None
                              and obs["hand"][action["card"]]["id"] == card)
            else:
                action, = [action for action in obs["actions"] if action["kind"] == "end_turn"]
            menu = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            powers = next(field for field in raw.split(";") if field.startswith("P="))
            assert ("FREE_ATTACK_POWER=1/" in powers) == free_attack, powers
            assert ("ILLUSION_POWER=1/" in powers) == illusion, powers
            dead = index == len(actions) - 1
            assert episode["status"] == ("death" if dead else "active")
            assert menu["decision"] == ("game_over" if dead else "combat_play")
            frames.append(dict(action=card or "end_turn", status=episode["status"],
                               stamp=stamp, powers=powers))
        pred.request("i1_n2_close")
    return dict(spec=spec, frames=frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    cases = [
        verify(output, versions, "FOGMOG_NORMAL", "OVERGROWTH", ("UNRELENTING", None, None),
               ((True, False), (True, True), (True, True))),
        verify(output, versions, "FOGMOG_NORMAL", "OVERGROWTH",
               ("UNRELENTING", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD", None, None),
               ((True, False), (True, False), (False, False), (False, True), (False, True))),
        verify(output, versions, "LIVING_FOG_NORMAL", "UNDERDOCKS", ("UNRELENTING", None),
               ((True, False), (False, False))),
    ]
    shadow["save_json"](output / "lifecycle.json", dict(engine=versions, cases=cases))
