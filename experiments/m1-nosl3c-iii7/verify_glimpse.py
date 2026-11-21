"""Compare Glimpse Beyond generation against independent native play."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_root import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade, play_glimpse):
    spec = dict(schema=3, act=1, act_variant="OVERGROWTH", character="Necrobinder",
                ascension=0, hp=75, max_hp=75, encounter="FLYCONID_NORMAL",
                seed="III7_GLIMPSE", relics=[], potions=[],
                deck=[dict(id="GLIMPSE_BEYOND", upgrade=upgrade) for _ in range(3)] +
                     [dict(id="DEFEND_NECROBINDER", upgrade=0) for _ in range(3)] +
                     [dict(id="STRIKE_NECROBINDER", upgrade=0) for _ in range(2)])
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False,
                               rejected=[])["episode"]

        def native_state():
            return native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]

        def draw_and_rng(raw):
            fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
            return {key: fields[key] for key in ("D", "R")}

        before = draw_and_rng(native_state())
        assert before["D"] and "SOUL+" not in before["D"]
        live = b["public_root"]
        obs = targets.project(episode["observation"])
        slots = target_indices(pred, native)
        iig.audit.compare_menu(obs, live, slots)
        card = "GLIMPSE_BEYOND" if play_glimpse else "DEFEND_NECROBINDER"
        action = next(a for a in obs["actions"] if a["card"] is not None
                      and obs["hand"][a["card"]]["id"] == card)
        live = native_step(native, action, slots, [])
        episode = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
        assert episode["status"] == "active" and live["decision"] == "combat_play"
        raw = native_state()
        stamp = sha256(raw.encode()).hexdigest()
        assert stamp == episode["audit_stamp"], targets.field_diff(
            pred.request("i1_iid_prediction_text")["text"], raw)
        after = draw_and_rng(raw)
        if play_glimpse:
            assert after["D"].count("SOUL+0/") == 3 + upgrade
            assert after["R"] != before["R"]
        else:
            assert after == before
        iig.audit.compare_menu(targets.project(episode["observation"]), live,
                               target_indices(pred, native))
        pred.request("i1_n2_close")
    return dict(spec=spec, action=card, before=before, after=after, stamp=stamp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    shadow["save_json"](output / "glimpse.json", dict(
        engine=versions, cases=[verify(output, versions, upgrade, play)
                                for upgrade, play in ((0, False), (0, True), (1, True))]))
