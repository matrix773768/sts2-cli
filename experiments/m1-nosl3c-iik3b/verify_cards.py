"""Exercise four card effects in reduced independent native combat fixtures."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

from verify_roots import CASES, tools
from probe_prefix import native_step, target_indices


def check(output, versions, index, deck, route, overrides=None):
    targets = tools["targets"]
    suite, step, root, _ = CASES[index]
    spec = tools["batch"](f"iij5b-serial-{suite}", step, root)["spec"]
    spec = spec | (overrides or {}) | {"deck": [dict(id=card, upgrade=upgrade) for card, upgrade in deck]}
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=32, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        for card, upgrade in route:
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            tools["compare_menu"](obs, live, slots)
            options = [action for action in obs["actions"]
                       if (action["kind"] == "end_turn" if card is None else
                           action["card"] is not None and
                           (obs["hand"][action["card"]]["id"], obs["hand"][action["card"]]["upgrade"])
                           == (card, upgrade))]
            if not options:
                return frames + [dict(action=card, unavailable=True, hand=obs["hand"], energy=obs["energy"])]
            live = native_step(native, options[0], slots, [])
            state = pred.request("i1_n2_step", position=state["actions"], index=options[0]["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")["state"][0]
            raw = frame["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            diffs = {} if stamp == state.get("audit_stamp") else targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
            frames.append(dict(action=card, status=state["status"], differences=diffs, stamp=stamp,
                               player_hp=live.get("player", {}).get("hp"), discard=live.get("discard_pile_count"),
                               block=live.get("player", {}).get("block"),
                               enemies=[e["hp"] for e in live.get("enemies", [])],
                               powers=fields["P"], hand=[c["id"] for c in live.get("hand", [])]))
            if diffs or state["status"] != "active":
                break
        pred.request("i1_n2_close")
    return frames


FIXTURES = {
    "sneaky": (0, [("SNEAKY", 0), ("SNEAKY", 1), ("STRIKE_SILENT", 0)] + [("DEFEND_SILENT", 0)] * 2,
               [("SNEAKY", 0), ("STRIKE_SILENT", 0), (None, 0), ("SNEAKY", 1)]),
    "one-for-all": (1, [("ONE_FOR_ALL", 0), ("ONE_FOR_ALL", 1), ("FTL", 0),
                       ("STRIKE_DEFECT", 0), ("DEFEND_DEFECT", 0)],
                    [("ONE_FOR_ALL", 0), ("ONE_FOR_ALL", 1), ("FTL", 0), ("STRIKE_DEFECT", 0)]),
    "tank": (2, [("TANK", 0)] + [("DEFEND_IRONCLAD", 0)] * 4, [("TANK", 0), (None, 0)]),
    "blade": (3, [("BLADE_SYMPHONY", 0), ("BLADE_SYMPHONY", 1), ("ADRENALINE", 0)]
              + [("DEFEND_SILENT", 0)] * 2,
              [("ADRENALINE", 0), ("BLADE_SYMPHONY", 0), ("BLADE_SYMPHONY", 1)]),
    "blade-cap": (3, [("BLADE_SYMPHONY", 0), ("BLADE_SYMPHONY", 1), ("BLADE_SYMPHONY", 1),
                      ("ADRENALINE", 1), ("BLADE_SYMPHONY", 1)] + [("DEFEND_SILENT", 0)] * 3,
                  [("ADRENALINE", 1), ("BLADE_SYMPHONY", 0), ("BLADE_SYMPHONY", 1),
                   ("BLADE_SYMPHONY", 1), ("BLADE_SYMPHONY", 1)], {"schema": 2, "relics": ["RING_OF_THE_SNAKE"]}),
    "one-for-all-reduced": (1, [("ONE_FOR_ALL", 0), ("BULLET_TIME", 1), ("STRIKE_DEFECT", 0),
                               ("SKEWER", 0), ("DEFEND_DEFECT", 0)],
                            [("BULLET_TIME", 1), ("ONE_FOR_ALL", 0), ("STRIKE_DEFECT", 0), ("SKEWER", 0)],
                            {"schema": 1, "act": 1, "act_variant": None, "encounter": "FLYCONID_NORMAL"}),
    "one-for-all-auto": (1, [("ONE_FOR_ALL", 1), ("HAVOC", 1)] + [("STRIKE_DEFECT", 0)] * 4,
                         [("ONE_FOR_ALL", 1), ("HAVOC", 1)],
                         {"schema": 1, "act": 1, "act_variant": None, "encounter": "FLYCONID_NORMAL"}),
    "one-for-all-auto-zero": (1, [("ONE_FOR_ALL", 1), ("HAVOC", 1)] + [("FTL", 0)] * 4,
                              [("ONE_FOR_ALL", 1), ("HAVOC", 1)],
                              {"schema": 1, "act": 1, "act_variant": None, "encounter": "FLYCONID_NORMAL"}),
    "tank-osty": (2, [("TANK", 1), ("BODYGUARD", 0), ("OFFERING", 0)] + [("DEFEND_NECROBINDER", 0)] * 2,
                  [("BODYGUARD", 0), ("TANK", 1), ("OFFERING", 0), (None, 0)],
                  {"schema": 1, "act_variant": None, "encounter": "FLYCONID_NORMAL",
                   "character": "Necrobinder"}),
}


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:3])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    for name in sys.argv[3:] or FIXTURES:
        start = perf_counter()
        frames = check(output, versions, *FIXTURES[name])
        seconds = perf_counter() - start
        tools["save_json"](output / f"{name}.json", dict(frames=frames, seconds=seconds, engine=versions))
        print(name, seconds, [(f["action"], f.get("status"), list(f.get("differences", {})),
                              f.get("unavailable", False)) for f in frames], flush=True)
        assert len(frames) == len(FIXTURES[name][2]), (name, frames[-1])
        assert all(f.get("status") == "active" and not f["differences"] for f in frames), name
