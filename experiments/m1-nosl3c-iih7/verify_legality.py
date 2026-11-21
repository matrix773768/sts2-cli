"""Compare native and predicted resource legality before and after Void Form."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import runpy

from replay import bind

shadow = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            "m1-nosl3c-iih4/verify_shadow.py"))
iig, targets = (shadow[name] for name in ("iig", "targets"))
native_step, target_indices = (shadow[name] for name in ("native_step", "target_indices"))


def verify(output, versions):
    spec = dict(schema=3, act=2, act_variant="HIVE", character="Regent",
                ascension=0, hp=75, max_hp=75, encounter="HUNTER_KILLER_NORMAL",
                seed="IIH7_STAR_COST", relics=[], potions=[],
                deck=[dict(id=card, upgrade=upgrade) for card, upgrade in
                      (("VOID_FORM", 1), ("THE_SMITH", 1), ("GENESIS", 0),
                       ("DEFEND_REGENT", 0), ("CONVERGENCE", 0))])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=6, potions=False,
                               rejected=[])["episode"]
        menu = b["public_root"]
        actions = ("VOID_FORM", "DEFEND_REGENT", "CONVERGENCE", None)
        for index, (card, smith_legal) in enumerate(zip(actions, (False, True, True, False), strict=True)):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, menu, slots)
            smith, = [row for row in menu["hand"] if row["id"] == "CARD.THE_SMITH"]
            assert smith["can_play"] == smith_legal
            assert smith.get("star_cost", 0) == (0 if smith_legal else 4)
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            if index:
                assert stamp == episode["audit_stamp"], targets.field_diff(
                    pred.request("i1_iid_prediction_text")["text"], raw)
            frames.append(dict(after=actions[index - 1] if index else None, stamp=stamp,
                               stars=menu.get("stars", 0), smith_legal=smith_legal,
                               smith_star_cost=smith.get("star_cost", 0)))
            if card is None:
                break
            action, = [action for action in obs["actions"] if action["card"] is not None
                       and obs["hand"][action["card"]]["id"] == card]
            menu = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
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
    shadow["save_json"](output / "legality.json", dict(engine=versions, **verify(output, versions)))
