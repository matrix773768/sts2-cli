"""Replay every frozen Sovereign Blade action against independent native state."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from verify_forge import bind, iig, targets, native_step, target_indices, shadow
from compare_frozen import entries
from replay_frozen import key


def verify(output, versions, ledger):
    _, _, batch = next(item for item in entries(ledger) if item[:2] == (0, "000003"))
    row, = batch["rows"]
    route = row["transitions"]
    assert len(route) == 29
    stamps = []
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, batch["spec"])
        b, _ = targets.CAPTURE(native, batch["spec"])
        assert a["native"] == b["native"]
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=32, potions=False,
                               rejected=[])["episode"]
        live = b["public_root"]
        selected = []
        correction = None
        for index, frozen in enumerate(route):
            obs = targets.project(episode["observation"])
            slots = {} if obs["decision"]["phase"] == "choice" else target_indices(pred, native)
            iig.audit.compare_menu(obs, live, slots)
            archived = frozen["observation"]
            if index == 28:
                blade = obs["hand"][-1]
                assert blade["id"] == "SOVEREIGN_BLADE" and live["hand"][-1]["id"] == "CARD.SOVEREIGN_BLADE"
                assert archived["hand"] + [blade] == obs["hand"]
                correction = dict(position=index, added_card=blade, archived_action=frozen["action"])
                archived = archived | {"hand": archived["hand"] + [blade]}
            assert all(obs[name] == value for name, value in archived.items() if name != "actions"), index
            action, = [action for action in obs["actions"] if key(action) == key(frozen["action"])]
            assert {k: v for k, v in action.items() if k != "index"} == {
                k: v for k, v in frozen["action"].items() if k != "index"
            }, index
            live = native_step(native, action, slots, selected) or live
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            if live["decision"] != "card_select":
                frame = native.request("i1_iib_native_stamp")
                raw = frame["state"][0]["exact_continuation_state"]
                stamp = sha256(raw.encode()).hexdigest()
                assert stamp == episode["audit_stamp"], (index, targets.field_diff(
                    pred.request("i1_iid_prediction_text")["text"], raw))
                stamps.append(dict(position=index, stamp=stamp, terminal=frame["terminal"]))
        if episode["status"] == "active":
            iig.audit.compare_menu(targets.project(episode["observation"]), live,
                                   target_indices(pred, native))
        pred.request("i1_n2_close")
    return dict(actions=len(route), final_status=episode["status"], native_decision=live["decision"],
                corrected_archived_hand=correction, matched_boundaries=stamps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    shadow["save_json"](output / "history.json",
                        dict(engine=versions, **verify(output, versions, args.ledger)))
