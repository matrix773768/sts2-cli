"""Public labels. Single stochastic realizations supervise conditional means."""
from features import MASSIVE_HP, powers, public_summary, variant


DELTA_WIDTH = 16
OUTCOME_WIDTH = 6


def transition_summary(obs):
    costs = [card["cost"] for card in obs["hand"] if card["cost"] is not None]
    return [*public_summary(obs), *powers(obs), len(obs["discard"])/25, len(obs["exhaust"])/25,
            sum(costs)/(5*max(1,len(costs)))]


def scoped_order(obs):
    """Local two-play gross HP-loss comparison for an unmodified enemy."""
    if obs["decision"]["phase"] != "combat" or obs["relics"] or any(obs["potions"]):
        return None
    if any(p["id"] != "STRENGTH_POWER" for p in obs["powers"]):
        return None
    strength = sum(p["amount"] for p in obs["powers"])
    hand = {c["index"]: c for c in obs["hand"]}
    enemies = {e["index"]: e for e in obs["enemies"]}
    buffs, attacks = [], []
    for a in obs["actions"]:
        if a["kind"] != "play_card" or a["cost"] is None or a.get("energy_x"):
            continue
        card = hand[a["card"]]
        if card.get("enchantment") is not None or card.get("affliction") is not None:
            continue
        qualification, rule = variant(card["id"], card["upgrade"])
        effects = rule.get("effects", ())
        if qualification != "static_described" or len(effects) != 1:
            continue
        effect, = effects
        if effect["kind"] == "GainPower" and effect.get("power") == "strength" and effect["target"] == "self":
            buffs.append((a, effect["amount"]))
        enemy = enemies.get(a["target"])
        if (effect["kind"] == "Damage" and effect["target"] == "selected_enemy"
                and "strength_per_hit" in effect.get("modifiers", ()) and a.get("target_side") == "enemy"
                and enemy and 0 < enemy["hp"] < MASSIVE_HP and not enemy["powers"] and enemy["block"] == 0):
            attacks.append((a, effect, enemy))
    for buff, amount in buffs:
        for attack, effect, enemy in attacks:
            before = max(0, effect["amount"]+strength) * effect["hits"]
            after = max(0, effect["amount"]+strength+amount) * effect["hits"]
            if buff["card"] == attack["card"] or buff["cost"]+attack["cost"] > obs["energy"]:
                continue
            if len(enemies) == 1 and before >= enemy["hp"]:
                # Guaranteed no-block lethal reaches the local terminal boundary
                # in one play, rather than spending a pre-action on Strength.
                if enemy["hp"] > 0:
                    return attack["index"], buff["index"]
            if before < after < enemy["hp"]:
                return buff["index"], attack["index"]
    return None


def labels(trajectory, index, order, source):
    step = trajectory["steps"][index]
    obs = step["observation"]
    terminal = trajectory["terminal"]
    after = trajectory["steps"][index+1]["observation"] if index+1 < trajectory["length"] else None
    # Terminal observations have a different schema. Delta loss only uses
    # pairs on the same public turn and on regular combat decision boundaries.
    delta_mask = after is not None and obs["turn"] == after["turn"] and (
        obs["decision"]["phase"] == after["decision"]["phase"] == "combat")
    delta = [b-a for a,b in zip(transition_summary(obs), transition_summary(after))] if delta_mask else [0.]*DELTA_WIDTH
    if order and index % 2:
        order = order[::-1]
    return dict(chosen=step["action"]["index"], source=source, pair=order or (0, 0),
                order=float(index % 2 == 0), order_mask=order is not None, delta=delta, delta_mask=delta_mask,
                outcome=[float(trajectory["status"] == "predicted_win"), terminal["hp"]/terminal["max_hp"],
                         trajectory["cumulative_loss"]/terminal["max_hp"],
                         float(trajectory["status"] == "death" and trajectory["length"]-index <= 4),
                         sum(p is not None for p in terminal["potions"])/3, terminal["gold"]/100])
