"""Replay the two Crawlers reversal witnesses with native Headless actions."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sys
import time

from analyze import prefix
from run import DOTNET, HERE, load

REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "python"))
from engine_client import EngineClient

ENEMIES = {1: "Shrinker Beetle", 2: "Fuzzy Wurm Crawler"}
HAND = ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD",
        "STRIKE_IRONCLAD", "STRIKE_IRONCLAD"]


def snapshot(state):
    return dict(playerHp=state["player"]["hp"], block=state["player"]["block"],
                energy=state["energy"], enemyHp=sum(e["hp"] for e in state["enemies"]))


def replay(item, log_root, deadline):
    with closing(EngineClient(log_root=log_root, command_timeout=22, deadline=deadline)) as engine:
        def send(cmd, **fields):
            state = engine.send({"cmd": cmd, **fields})
            if state.get("type") == "error":
                raise RuntimeError(state)
            return state

        send("start_run", character="Ironclad", seed="run_2", ascension=0, lang="en")
        state = send("enter_room", type="combat", encounter="OVERGROWTH_CRAWLERS")
        assert snapshot(state) == dict(playerHp=80, block=0, energy=3, enemyHp=96)
        assert [card["id"] for card in state["hand"]] == ["CARD." + card for card in HAND]
        assert [(enemy["name"], enemy["hp"]) for enemy in state["enemies"]] == [
            (ENEMIES[1], 39), (ENEMIES[2], 57)
        ]
        first = None
        route = item["witness"]
        for i, action in enumerate(route, 1):
            assert state["decision"] == "combat_play", (i, state["decision"])
            assert state["round"] == action["turn"], (i, state["round"], action["turn"])
            if action["kind"] == "EndTurn":
                state = send("action", action="end_turn")
            elif action["kind"] == "PlayCard":
                assert not action["choice"] and not action["nestedChoices"]
                copies = [c for c in state["hand"] if c["id"] == "CARD." + action["cardId"]]
                card = copies[action["cardOccurrence"]]
                args = {"card_index": card["index"]}
                target = action["targetCombatId"]
                if target is not None and card["target_type"] == "AnyEnemy":
                    args["target_index"] = next(e["index"] for e in state["enemies"]
                                                if e["name"] == ENEMIES[target] and e["hp"] > 0)
                state = send("action", action="play_card", args=args)
            else:
                raise ValueError(action["kind"])
            if i == 1:
                first = snapshot(state)
                assert first == {key: item[key] for key in first}, (first, item["action"])
        assert state["decision"] == "card_reward", state["decision"]
        # This no-potion starter deck heals exactly six HP through Burning Blood.
        expected = min(80, 80 - item["quality"]["projectedBattleHpLost"] + 6)
        assert state["player"]["hp"] == expected, (state["player"]["hp"], expected)
        return {"actions": len(route), "firstStep": first, "postCombatHp": expected,
                "terminal": state["decision"], "plan": [
                    {key: action[key] for key in ("kind", "turn", "cardId", "cardOccurrence", "targetCombatId")}
                    for action in route
                ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    os.environ["STS2_DOTNET"] = str(DOTNET)
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    folder = args.output / "prefix/crawlers/1200"
    report, _ = prefix(folder)
    pair, = [p for p in report["strict"] if p["scoreReversal"] and p["beamReversal"]]
    rows = load(folder / "candidates.json")["rows"]
    deadline = time.monotonic() + 85
    verified = {}
    for side in ("better", "worse"):
        key = pair[side]
        row, = [row for row in rows if row["action"]["cardId"] == report["rows"][key]["action"]["cardId"]
                and row["action"]["targetCombatId"] == report["rows"][key]["action"]["targetCombatId"]]
        verified[key] = replay(row, args.output / "native", deadline)
    print(json.dumps({"root": "crawlers", "nodes": 1200, "pair": pair, "native": verified}, indent=2))


if __name__ == "__main__":
    main()
