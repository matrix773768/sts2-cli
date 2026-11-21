"""Compare Outrage cloning before and after the terminal attack."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_root import bind
from verify_legality import iig, targets, native_step, target_indices, shadow


def verify(output, versions, upgrade):
    spec = dict(schema=3, act=1, act_variant="UNDERDOCKS", character="Ironclad",
                ascension=0, hp=75, max_hp=75, encounter="SLUDGE_SPINNER_WEAK",
                seed="III4_OUTRAGE", relics=[], potions=[],
                deck=[dict(id=card, upgrade=level) for card, level in
                      [("OUTRAGE", upgrade)] + [("DEFEND_IRONCLAD", 0)] * 4])
    frames = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=20, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        count = 1
        for index in range(20):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            attacks = [a for a in obs["actions"] if a["card"] is not None
                       and obs["hand"][a["card"]]["id"] == "OUTRAGE" and a["target"] == 0]
            action = attacks[0] if attacks else next(a for a in obs["actions"] if a["kind"] == "end_turn")
            before_hp = live["enemies"][0]["hp"]
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            frame = native.request("i1_iib_native_stamp")
            raw = frame["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            fields = [field for field in raw.split(";") if f"OUTRAGE+{upgrade}" in field]
            after = sum(field.count(f"OUTRAGE+{upgrade}") for field in fields)
            # The terminal stamp leaves the played card outside the stamped piles.
            expected = count - 1 if frame["terminal"] else count + int(bool(attacks))
            assert after == expected, (action, frame["terminal"], count, fields)
            frames.append(dict(action="OUTRAGE" if attacks else "end_turn", stamp=stamp,
                               enemy_hp_before=before_hp, terminal=frame["terminal"],
                               count_before=count, count_after=after, outrage_fields=fields))
            count = after
            if frame["terminal"]:
                assert episode["status"] == "predicted_win" and live["decision"] == "card_reward"
                break
            assert episode["status"] == "active" and live["decision"] == "combat_play"
        pred.request("i1_n2_close")
    assert frames[-1]["terminal"] and frames[-1]["action"] == "OUTRAGE"
    assert frames[0]["count_after"] == 2
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
    shadow["save_json"](output / "outrage.json", dict(engine=versions,
                       cases=[verify(output, versions, upgrade) for upgrade in (0, 1)]))
