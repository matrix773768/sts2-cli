"""Deterministic policies for supported room decisions."""


def action(name, **args):
    return {"action": name, "args": args}


def combat_action(state):
    for card in state["hand"]:
        if card["can_play"] and card["cost"] <= state["energy"]:
            args = {"card_index": card["index"]}
            if card["target_type"] == "AnyEnemy":
                target = next((e for e in state["enemies"] if e["hp"] > 0), None)
                if target is None:
                    continue
                args["target_index"] = target["index"]
            return action("play_card", **args)
    return action("end_turn")


def reward_action(state):
    """Take the first offered card from a normal combat reward."""
    if state.get("from_event") or "gold_earned" not in state:
        return None
    if state["cards"]:
        return action("select_card_reward", card_index=state["cards"][0]["index"])
    if state.get("can_skip") is True:
        return action("skip_card_reward")
    return None
