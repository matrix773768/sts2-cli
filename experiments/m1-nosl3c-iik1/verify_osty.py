"""Compare Osty's attack count after a new turn and resurrection."""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

from verify_route import tools
from probe_prefix import native_step, target_indices


def check(output, versions):
    targets = tools["targets"]
    spec = tools["batch"]("iij5b-serial-pair16", 0, "000009")["spec"]
    spec = spec | {"encounter": "FLYCONID_NORMAL", "deck": [{"id": card, "upgrade": upgrade} for card, upgrade in
                           [("LEGION_OF_BONE", 1), ("RATTLE", 0), ("RATTLE", 1),
                            ("LEGION_OF_BONE", 1), ("LEGION_OF_BONE", 1)]]}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        state = pred.request("i1_n2_reset", arm="A", cap=16, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        frames = []
        for card, hits in [("LEGION_OF_BONE", None), ("RATTLE", 1),
                           (None, None), ("LEGION_OF_BONE", None), ("RATTLE", 1)]:
            obs = targets.project(state["observation"])
            slots = target_indices(pred, native)
            tools["compare_menu"](obs, live, slots)
            if card == "RATTLE":
                assert next(c for c in live["hand"] if c["id"] == "CARD.RATTLE")[
                    "stats"]["calculatedhits"] == hits
            actions = [a for a in obs["actions"] if (
                a["kind"] == "end_turn" if card is None else
                a["card"] is not None and obs["hand"][a["card"]]["id"] == card
                and (card != "RATTLE" or a["target"] == 1))]
            assert actions, (card, obs["hand"], obs["energy"])
            action = actions[0]
            live = native_step(native, action, slots, [])
            state = pred.request("i1_n2_step", position=state["actions"],
                                 index=action["index"])["episode"]
            raw = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            differences = {} if stamp == state["audit_stamp"] else targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            frames.append(dict(card=card, native_hits=hits, stamp=stamp, differences=differences,
                               native_enemies=live["enemies"],
                               osty=next(field for field in raw.split(";") if field.startswith("osty="))))
            if differences:
                break
        pred.request("i1_n2_close")
    return frames


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    frames = check(output, versions)
    tools["save_json"](output / "fixture.json", dict(engine=versions, frames=frames))
    print([(frame["card"], frame["native_hits"], list(frame["differences"])) for frame in frames])
