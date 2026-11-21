"""Verify the native Bloat entrance and nonlethal explosion against prediction."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import runpy

shadow = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            "m1-nosl3c-iih4/verify_shadow.py"))
bind, iig, targets = (shadow[name] for name in ("bind", "iig", "targets"))
native_step, target_indices = (shadow[name] for name in ("native_step", "target_indices"))


def verify(output, versions):
    spec = dict(schema=3, act=1, act_variant="UNDERDOCKS", character="Ironclad",
                ascension=0, hp=80, max_hp=80, encounter="LIVING_FOG_NORMAL",
                seed="IIH5_BLOAT", relics=[], potions=[],
                deck=[dict(id="DEFEND_IRONCLAD", upgrade=0)] * 5)
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=5, potions=False,
                               rejected=[])["episode"]
        menu = b["public_root"]
        for index in range(3):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, menu, slots)
            action, = [action for action in obs["actions"] if action["kind"] == "end_turn"]
            menu = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            assert menu["decision"] == "combat_play" and not frame["terminal"]
            assert episode["status"] == "active"
            assert sha256(raw.encode()).hexdigest() == episode["audit_stamp"]
            fields = raw.split(";")
            bombs = [field for field in fields if "/GAS_BOMB/" in field]
            powers = next(field for field in fields if field.startswith("P="))
            assert bool(bombs) == (index == 1), bombs
            assert ("MINION_POWER=1/" in powers) == (index == 1), powers
            frames.append(dict(end_turn=index + 1, stamp=episode["audit_stamp"],
                               bombs=bombs, powers=powers))
        iig.audit.compare_menu(targets.project(episode["observation"]), menu,
                               target_indices(pred, native))
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
    shadow["save_json"](output / "lifecycle.json", dict(engine=versions, **verify(output, versions)))
