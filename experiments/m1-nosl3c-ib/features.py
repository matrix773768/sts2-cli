"""Equivalent public tensor construction with a bounded, parameter-free static cache."""
from functools import lru_cache
from pathlib import Path
import sys

import torch

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "m1-nosl3c"
sys.path.insert(0, str(BASE))
import protocol
from nosl_model import KINDS, INTENTS, PREVIEWS, EFFECT_SLOTS, powers, scalar, static, token


@lru_cache(maxsize=1024)
def card_rules(signature):
    rules = [static(card, upgrade) for card, upgrade in signature]
    return (
        torch.tensor([token(card) for card, _ in signature], dtype=torch.long),
        torch.tensor([r[0] for r in rules], dtype=torch.long).reshape(-1, 3 + EFFECT_SLOTS),
        torch.tensor([r[1] for r in rules], dtype=torch.float32).reshape(-1, 4 + 9 * EFFECT_SLOTS),
    )


class FastDecision:
    def __init__(self, obs):
        self.groups = [obs[k] for k in ("deck", "hand", "discard", "exhaust")]
        cards = [c for group in self.groups for c in group]
        self.actions = obs["actions"]
        hand = {c["index"]: i + len(self.groups[0]) + 1 for i, c in enumerate(self.groups[1])}
        enemies = {e["index"]: i + 1 for i, e in enumerate(obs["enemies"])}
        refs, kinds, potions, previews, costs = [], [], [], [], []
        for a in self.actions:
            refs.append([hand[a["card"]] if a["card"] is not None else 0,
                         hand[a["choice"]] if a["choice"] is not None else 0,
                         enemies[a["target"]] if a["target"] is not None else 0])
            kinds.append(KINDS.index(a["kind"]))
            potions.append(token(obs["potions"][a["potion"]]) if a["potion"] is not None else 0)
            preview = a["preview"] or {}
            previews.append([n for key in PREVIEWS for n in scalar(preview.get(key))])
            costs.append(scalar(a["cost"]))
        self.refs = torch.tensor(refs, dtype=torch.long)
        self.kind = torch.tensor(kinds)
        self.pots = torch.tensor(potions)
        self.preview, self.action_cost = torch.tensor(previews), torch.tensor(costs)
        playable = {a["card"] for a in self.actions}
        self.playable = torch.tensor([float(c["index"] in playable) for c in self.groups[1]])
        self.energy = obs["energy"]
        self.enemy = torch.tensor([[e["hp"] / 40, e["block"] / 20, sum(e["attack_hits"]) / 30,
                                    len(e["attack_hits"]) / 8, *powers(e["powers"]),
                                    *(float(i in e["intents"]) for i in INTENTS)]
                                   for e in obs["enemies"]], dtype=torch.float32).reshape(-1, 9 + len(INTENTS))
        self.relics = torch.tensor([token(r) for r in obs["relics"]], dtype=torch.long)
        self.inventory = torch.tensor([token(p) for p in obs["potions"]], dtype=torch.long)
        self.player = torch.tensor([obs["hp"] / obs["max_hp"], obs["max_hp"] / 100, obs["block"] / 30,
                                    self.energy / 5, obs["turn"] / 15, obs["draw_count"] / 20,
                                    len(obs["potions"]) / 5, *powers(obs["powers"]), 0.])
        self.card_ids, self.rule_ids, self.rule_values = card_rules(
            tuple((c["id"], c["upgrade"]) for c in cards))
        self.instance_ids = torch.tensor([[token(c["enchantment"]), token(c["affliction"])]
                                          for c in cards], dtype=torch.long).reshape(-1, 2)
        self.instance = torch.tensor([[c["upgrade"] / 2, *scalar(c["cost"]),
                                       *scalar(c["enchantment_amount"]), *scalar(c["affliction_amount"])]
                                      for c in cards], dtype=torch.float32).reshape(-1, 7)