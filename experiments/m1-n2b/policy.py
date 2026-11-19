"""Linear policy over the N2A.1 public observation contract."""
from math import fsum

FEATURES = ("play", "damage", "lethal", "removed_attack", "block", "draw", "cost",
            "growth", "target_hp", "missing_damage", "end_turn", "uncovered",
            "discard_defense", "discard_upgrade", "discard_growth")
GROWTH = {"INFLAME", "FOOTWORK", "ACCURACY"}
DEFENSE = {"FLAME_BARRIER", "DODGE_AND_ROLL", "SURVIVOR", "SHRUG_IT_OFF", "LEG_SWEEP"}


def features(obs, action, incoming):
    missing = max(0, incoming - obs.block)
    if action.card is None:
        return (0,) * 10 + (1, min(missing, 30)/30, 0, 0, 0)
    card = obs.hand[action.card]
    target = obs.enemies[action.target] if action.target is not None else None
    preview = action.preview
    known = target is not None and preview is not None and preview.damage_per_hit is not None
    damage = max(0, preview.damage_per_hit * preview.hits - target.block) if known else 0
    lethal = known and damage >= target.hp
    threat = sum(target.attack_hits) if lethal else 0
    block = min(missing, preview.block or 0) if preview else 0
    choice = action.choice
    return (
        1, min(damage, target.hp, 30)/30 if known else 0, int(lethal), min(threat, 30)/30,
        min(block, 30)/30, min(preview.draw or 0, 3)/3 if preview else 0,
        min(max(action.cost or 0, 0), 3)/3, int(card.id in GROWTH),
        min(target.hp, 40)/40 if target else 0, int(target is not None and not known),
        0, 0, int(choice is not None and (choice.id.startswith("DEFEND") or choice.id in DEFENSE)),
        min(choice.upgrade, 2)/2 if choice else 0, int(choice is not None and choice.id in GROWTH),
    )


def decide(obs, actions, weights):
    incoming = sum(sum(enemy.attack_hits) for enemy in obs.enemies)
    # max preserves the first legal menu entry on ties.
    return max(actions, key=lambda a: fsum(w*f for w, f in zip(weights, features(obs, a, incoming), strict=True)))
