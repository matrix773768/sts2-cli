"""Compare Plot's delayed draw against independent native combat."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_root import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade, play_plot):
    spec = dict(schema=3, act=1, act_variant="OVERGROWTH", character="Regent",
                ascension=0, hp=75, max_hp=75, encounter="FLYCONID_NORMAL",
                seed="III8_PLOT", relics=[], potions=[],
                deck=[dict(id="PLOT", upgrade=upgrade) for _ in range(3)] +
                     [dict(id="DEFEND_REGENT", upgrade=0) for _ in range(5)] +
                     [dict(id="STRIKE_REGENT", upgrade=0) for _ in range(6)])
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False,
                               rejected=[])["episode"]
        live = b["public_root"]

        def state():
            raw = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
            fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
            return raw, {key: fields[key] for key in ("D", "P", "R")}

        _, before = state()
        frames = []
        for index, card in enumerate(("PLOT" if play_plot else "DEFEND_REGENT", None)):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            if card is None:
                action, = [a for a in obs["actions"] if a["kind"] == "end_turn"]
            else:
                action = next(a for a in obs["actions"] if a["card"] is not None
                              and obs["hand"][a["card"]]["id"] == card)
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            assert episode["status"] == "active" and live["decision"] == "combat_play"
            raw, fields = state()
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            frames.append(dict(action=card or "end_turn", stamp=stamp, hand=len(live["hand"]), **fields))

        played, next_turn = frames
        power = "DRAW_CARDS_NEXT_TURN_POWER="
        assert played["D"] == before["D"] and played["R"] == before["R"]
        if play_plot:
            assert f"{power}{2 + upgrade}/" in played["P"]
        else:
            assert power not in played["P"]
        assert power not in next_turn["P"]
        assert next_turn["hand"] == 5 + (2 + upgrade if play_plot else 0)
        iig.audit.compare_menu(targets.project(episode["observation"]), live,
                               target_indices(pred, native))
        pred.request("i1_n2_close")
    return dict(spec=spec, before=before, frames=frames)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    shadow["save_json"](output / "plot.json", dict(
        engine=versions, cases=[verify(output, versions, upgrade, play)
                                for upgrade, play in ((0, False), (0, True), (1, True))]))
