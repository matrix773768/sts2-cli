"""Strict observable-state comparison and a small, deterministic combat policy."""


def first_difference(expected, actual, path="$"):
    if type(expected) is not type(actual):
        return f"{path}: expected {expected!r}, actual {actual!r}"
    if isinstance(expected, dict):
        for key in sorted(expected.keys() | actual.keys()):
            child = f"{path}.{key}"
            if key not in expected:
                return f"{child}: expected <missing>, actual {actual[key]!r}"
            if key not in actual:
                return f"{child}: expected {expected[key]!r}, actual <missing>"
            diff = first_difference(expected[key], actual[key], child)
            if diff:
                return diff
    elif isinstance(expected, list):
        for index, (left, right) in enumerate(zip(expected, actual)):
            diff = first_difference(left, right, f"{path}[{index}]")
            if diff:
                return diff
        if len(expected) != len(actual):
            return f"{path}.length: expected {len(expected)}, actual {len(actual)}"
    elif expected != actual:
        return f"{path}: expected {expected!r}, actual {actual!r}"
    return None


def assert_same(expected, actual, step):
    diff = first_difference(expected, actual)
    assert diff is None, f"step {step}: {diff}"


def combat_action(state):
    """Use exported legality flags; no guessed card IDs, costs, or enemy IDs."""
    assert state["decision"] == "combat_play", state
    for card in state["hand"]:
        if not card["can_play"] or card["cost"] > state["energy"]:
            continue
        args = {"card_index": card["index"]}
        if card["target_type"] == "AnyEnemy":
            enemies = [enemy for enemy in state["enemies"] if enemy["hp"] > 0]
            if not enemies:
                continue
            args["target_index"] = enemies[0]["index"]
        return {"cmd": "action", "action": "play_card", "args": args}
    return {"cmd": "action", "action": "end_turn"}
