"""Exercise Prepared on a separately labeled native fixture."""
import argparse
from pathlib import Path

from benchmark import f1, Session


def prepared(output, hand_order):
    with Session(output) as game:
        game.request("start_run", character="Silent", ascension=0, seed="f2-prepared", lang="en")
        game.execute_action({"action": "leave_room"})
        game.request("set_player", deck=["PREPARED"] * 6 + ["STRIKE_SILENT", "DEFEND_SILENT"] * 2)
        state = game.request("enter_room", type="combat", encounter="SHRINKER_BEETLE_WEAK")
        root = game.request("f1_begin")
        card = next(c for c in state["hand"] if c["id"] == "CARD.PREPARED" and c["can_play"])
        step = game.request("f1_step", step=1, audit=True, force={"action": "play_card",
                             "args": {"card_index": card["index"]}},
                            **({"hand_order_discard": True} if hand_order else {}))
        assert step["decision"]["decision"] == "combat_play", step
        assert not step.get("choice_failure"), step
        request, = step["choice_requests"]
        check, = [row for row in step["choice_checks"] if "discard" in row]
        assert request["action"] == "PREPARED" and request["min_select"] == request["max_select"] == 1
        assert check["discard"] and check["instances"][0]["option"] == request["indexes"][0]
        assert check["rng_at_choice"] == check["rng_after"]
        assert len(step["decision"]["hand"]) == len(state["hand"]) - 1
        next_turn = game.execute_action({"action": "end_turn"})
        assert next_turn["decision"] == "combat_play" and next_turn["round"] == state["round"] + 1
        return dict(root=root["live"], hand_order=hand_order, request=request, check=check,
                    pre_audit=step["pre_audit"], post_audit=step["post_audit"],
                    next_turn=next_turn["round"], next_audit=game.request("f1_audit"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    f1.DLL = f1.ROOT / "logs/m1-f2-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    f1.setup(out)
    results = []
    for hand_order in (True, False):
        first = prepared(out, hand_order)
        assert first == prepared(out, hand_order)
        results.append(first)
    assert results[0]["root"] == results[1]["root"]
    f1.write(out / "prepared.json", results)
    print("Prepared: two policies, four isolated native replays, exact repeat parity")


if __name__ == "__main__":
    main()
