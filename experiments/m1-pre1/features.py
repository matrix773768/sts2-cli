"""Feature contract for a public Ironclad decision, shared by learner and actor."""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE.parent / "m1-n2e/cards.json"
CATALOG = json.loads(CATALOG_PATH.read_bytes())["cards"]
RULES = {card["id"]: card for card in CATALOG}
ZONES = ("deck", "hand", "discard", "exhaust", "candidates")
POWERS = ("STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "VULNERABLE_POWER", "FRAIL_POWER")
INTENTS = ("Attack", "Buff", "Debuff", "Defend", "Heal", "Status", "Summon", "Stun", "DeathBlow")
ACTIONS = ("play_card", "end_turn", "select_candidate", "confirm_selection", "use_potion")
EFFECTS = ("Damage", "Block", "Draw", "GainEnergy", "GainPower", "ApplyPower", "IncreaseEnergy",
           "Heal", "LoseHp", "Upgrade", "Exhaust", "Discard", "GenerateCard", "TriggeredEffect", "UnsupportedEffect")
MOD_BUCKETS = 512
HISTORY = 24
CARD_FEATURES = 8
ENEMY_FEATURES = 11 + len(INTENTS)
MASSIVE_HP = 10000
PLAYER_FEATURES = 23
ACTION_FEATURES = 16
SOURCE_HASHES = (
    "cb2130276dd73a62703a8a0b955b92809fdd7db3b23f8e10719f73d40a4006a9",
    "180b1141d52fe836d5b7770c90c7be193c1c9a8b86bfd7e152274f2e8cd540a6",
)


@lru_cache(maxsize=8192)
def token(text):
    return 0 if text is None else 1 + int.from_bytes(sha256(text.encode()).digest()[:4], "little") % (MOD_BUCKETS-1)


def powers(observation):
    public = {entry["id"]: entry["amount"] for entry in observation["powers"]}
    return [public.get(name, 0) / 10 for name in POWERS]


def value(raw, scale):
    return [0., 0.] if raw is None else [raw / scale, 1.]


def load_vocabulary(files):
    import sqlite3
    from contextlib import closing
    ids = set(RULES)
    for path in files:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)) as db:
            manifest = json.loads(db.execute("SELECT json FROM manifest").fetchone()[0])
            ids.update(manifest["allowed_cards"])
    return sorted(ids)


@lru_cache(maxsize=4096)
def variant(card_id, upgrade):
    card = RULES.get(card_id, {})
    details = next((data for data in card.get("variants", ()) if data["level"] == upgrade), None)
    return card.get("qualification", "unknown") if details else "unknown", details or {}


def static_table(vocabulary):
    # Ordered slots preserve the ordering of verified mechanism nodes. The final
    # bits describe absent, partial and overflowed rules explicitly.
    width = 7 + 4*(len(EFFECTS)+7)
    table = np.zeros((len(vocabulary)+2, 4, width), dtype=np.float32)
    table[1, :, 0] = 1
    for i, card in enumerate(vocabulary, 2):
        for upgrade in range(4):
            qualification, rule = variant(card, upgrade)
            effects = rule.get("effects", [])
            row = [float(qualification == "unknown"), float(qualification == "static_partial"),
                   float(qualification == "static_described"), float(len(effects) > 4),
                   *value(rule.get("cost"), 5), float(bool(rule.get("x_cost", False)))]
            for j in range(4):
                effect = effects[j] if j < len(effects) else {}
                kind = effect.get("kind")
                row.extend(float(kind == name) for name in EFFECTS)
                row.extend([*(float(effect.get(k, 0) or 0)/10 for k in ("amount", "hits", "count")),
                            float("strength_per_hit" in effect.get("modifiers", [])),
                            float(effect.get("power") == "strength"),
                            float(effect.get("target") == "selected_enemy"), float(bool(effect))])
            table[i, upgrade] = row
    return table


def public_summary(obs):
    return [obs["hp"]/max(1, obs["max_hp"]), obs["block"]/30, obs["energy"]/5,
            len(obs["hand"])/10, obs["draw_count"]/25,
            sum(e["hp"] for e in obs["enemies"] if e["hp"] < MASSIVE_HP)/200,
            sum(sum(e["attack_hits"]) for e in obs["enemies"])/50, obs["turn"]/30]


def history_step(memory, obs, action, card_id):
    history = np.asarray([*public_summary(obs), *powers(obs),
                          *(float(action["kind"] == name) for name in ACTIONS),
                          *(value(action.get("cost"), 5)),
                          float(action.get("target") is not None),
                          float(action.get("choice") is not None),
                          float(card_id == "INFLAME"), 1.], dtype=np.float32)
    # Three time scales, update from the executed public action only.
    return memory * np.asarray([[.0], [.75], [.97]], dtype=np.float32) + history * np.asarray(
        [[1.], [.25], [.03]], dtype=np.float32)


class Encoder:
    def __init__(self, vocabulary):
        self.vocabulary = vocabulary
        self.ids = {card: i for i, card in enumerate(vocabulary, 2)}

    @staticmethod
    def initial_history():
        return np.zeros((3, HISTORY), dtype=np.float32)

    def encode(self, obs, memory):
        cards, instances, modifiers, regions = [], [], [], []
        lookup = {}
        decision = obs["decision"]
        for zone, name in enumerate(ZONES):
            for card in decision.get(name, []) if name == "candidates" else obs[name]:
                lookup[(name, card["index"])] = len(cards)+1
                cards.append(self.ids.get(card["id"], 1))
                instances.append([min(3, card["upgrade"]), *value(card.get("cost"), 5),
                                  *value(card.get("enchantment_amount"), 10),
                                  *value(card.get("affliction_amount"), 10),
                                  float(name=="candidates" and card["index"] in decision.get("selected", ()))])
                modifiers.append([token(card.get("enchantment")), token(card.get("affliction"))])
                regions.append(zone+1)
        enemies = []
        enemy_lookup = {}
        for enemy in obs["enemies"]:
            enemy_lookup[enemy["index"]] = len(enemies)+1
            # Waterfall Giant can publish a sentinel near 1e9. Preserve a
            # separate visibility bit without dominating gradients.
            hp = enemy["hp"]
            enemies.append([min(hp, 1000)/100, enemy["block"]/30, sum(enemy["attack_hits"])/50,
                            len(enemy["attack_hits"])/8, float(hp >= MASSIVE_HP), *powers(enemy),
                            *(float(t in enemy["intents"]) for t in INTENTS),
                            float(any(t not in INTENTS for t in enemy["intents"]))])
        player = [*public_summary(obs), *powers(obs), obs["max_hp"]/1000,
                  len(obs["deck"])/30, len(obs["discard"])/30, len(obs["exhaust"])/30,
                  float(decision["phase"] == "choice"), decision.get("min", 0)/5,
                  decision.get("max", 0)/5, len(decision.get("selected", []))/5,
                  sum(p is not None for p in obs["potions"])/3, obs["stars"]/10]
        actions, action_refs = [], []
        for index, action in enumerate(obs["actions"]):
            if action["index"] != index or action["kind"] not in ACTIONS:
                raise ValueError("Unexpected public menu index or action kind")
            preview = action.get("preview") or {}
            action_refs.append([lookup.get(("hand", action["card"]), 0),
                                lookup.get(("candidates", action["choice"]), 0),
                                enemy_lookup.get(action["target"], 0) if action.get("target_side") == "enemy" else 0])
            actions.append([*(float(action["kind"] == k) for k in ACTIONS), *value(action["cost"], 5),
                            *(number for k in ("damage_per_hit", "hits", "block", "draw")
                              for number in value(preview.get(k), 20)), float(bool(action.get("energy_x")))])
        if not actions:
            raise ValueError("Decision without any legal action")
        return dict(cards=np.asarray([0, *cards], dtype=np.int16),
                    instances=np.asarray([[0.]*CARD_FEATURES, *instances], dtype=np.float32),
                    mods=np.asarray([[0, 0], *modifiers], dtype=np.int16),
                    zones=np.asarray([0, *regions], dtype=np.uint8),
                    enemies=np.asarray([[0.]*ENEMY_FEATURES, *enemies], dtype=np.float32),
                    actions=np.asarray(actions, dtype=np.float32), refs=np.asarray(action_refs, dtype=np.int16),
                    player=np.asarray(player, dtype=np.float32), history=memory,
                    choice=np.asarray([token(decision.get(k)) for k in ("effect", "pile", "timing")], dtype=np.int16))

    def update(self, memory, obs, action):
        card = next((card["id"] for card in obs["hand"] if card["index"] == action["card"]), None)
        return history_step(memory, obs, action, card)
