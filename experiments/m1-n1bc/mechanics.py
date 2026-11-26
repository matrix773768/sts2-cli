"""Public typed features, shared by live graph nodes, rollouts and replay."""
from functools import lru_cache
import gzip
import json
import numpy as np

from arena import HERE
from features import Encoder, ZONES, variant, token, CARD_FEATURES, PLAYER_FEATURES, ENEMY_FEATURES
import torch
from torch import nn

POWERS = ("RITUAL", "ARTIFACT", "PLATING", "INTANGIBLE", "THORNS", "METALLICIZE", "BARRICADE",
          "DARK_EMBRACE", "FEEL_NO_PAIN", "CORRUPTION", "DEMON_FORM", "RAGE", "FLAME_BARRIER",
          "NO_DRAW", "CURL_UP", "ENRAGE")
POWER_IDS = {p+"_POWER": i for i,p in enumerate(POWERS)}
CARD_WIDTH = 12
ENEMY_WIDTH = 32 + len(POWERS) + 8
PLAYER_WIDTH = 3 + len(POWERS) + 8


@lru_cache(maxsize=2)
def catalogs(wide=False):
    path = HERE.parent/"hotdraw/mechanisms/exports.json.gz"
    with gzip.open(path) as f:
        source = json.load(f)
    cards, graphs = {}, {}
    for entry in [*source["results"].values(), *source["enemyProbes"].values()]:
        public = entry["result"]["input"]
        for c in public["cardRules"]:
            cards[c["Entry"]] = c
        for e in public["enemyRules"]:
            # Only static topology. No captured damage or resolved successor.
            nodes = e["rules"].get("nodes", [])
            graphs[e["Entry"]] = (1., len(nodes)/16,
                sum(bool(n["next"]) for n in nodes)/16,
                sum(n["ConditionalKind"] != "None" for n in nodes)/8)
    if wide:
        with gzip.open(HERE/"catalog.json.gz") as f:
            broad = json.load(f)
        cards.update(broad["cards"])
        for species, nodes in broad["graphs"].items():
            graphs[species] = (1., len(nodes)/16, sum(bool(n["next"]) for n in nodes)/16,
                               sum(n["ConditionalKind"] != "None" for n in nodes)/8)
    return cards, graphs


@lru_cache(maxsize=4096)
def card_info(name, upgrade, wide=False):
    c = catalogs(wide)[0].get(name, {})
    _, v = variant(name, upgrade)
    kind = c.get("Type", v.get("type"))
    cost = v.get("cost") if not c else c["UpgradedCost" if upgrade else "BaseCost"]
    ops = c.get("operations", ())
    return cost, (float(bool(c)), float(kind == "Attack"), float(kind == "Skill"), float(kind == "Power"),
                  float(bool(kind)), float(c.get("HookMask", "None") != "None"), len(ops)/8,
                  float(c.get("coverage") == "specialized_execution_unexpanded"),
                  float(bool(c.get("CanGenerateUnknown"))), len(c.get("OrderedVarNames", ()))/8)


def stack_vector(stacks, owner):
    result = np.zeros(len(POWERS), np.float32)
    for p in stacks:
        if p["owner"] == owner:
            result[POWER_IDS[p["id"]]] += np.clip(p["amount"], -100, 100)/10
    return result


class PilotEncoder(Encoder):
    def __init__(self, vocabulary, enabled, wide=False):
        super().__init__(vocabulary)
        self.enabled = enabled
        self.wide = wide

    def encode(self, obs, memory):
        row = super().encode(obs, memory)
        cards = np.zeros((len(row["cards"]), CARD_WIDTH), np.float32)
        enemies = np.zeros((len(row["enemies"]), ENEMY_WIDTH), np.float32)
        player = np.zeros(PLAYER_WIDTH, np.float32)
        if self.enabled:
            m = obs["mechanism"]
            player[:3] = [m[k]/10 for k in ("played", "attacks", "skills")]
            player[3:3+len(POWERS)] = stack_vector(m["stacks"], -1)
            for name in obs["relics"]:
                player[3+len(POWERS)+token(name)%8] += 1
            i = 1
            for zone in ZONES:
                pile = obs["decision"].get(zone, []) if zone == "candidates" else obs[zone]
                for c in pile:
                    base, info = card_info(c["id"], c["upgrade"], self.wide)
                    known = base is not None and base >= 0 and c.get("cost") is not None
                    cards[i] = (*info, float(known), (c["cost"]-base)/5 if known else 0.)
                    i += 1
            for i, (enemy, species) in enumerate(zip(obs["enemies"], m["species"], strict=True), 1):
                if species:
                    enemies[i,token(species)%32] = 1
                enemies[i,32:32+len(POWERS)] = stack_vector(m["stacks"], enemy["index"])
                hits = enemy["attack_hits"]
                enemies[i,-8:-4] = (list(hits[:4])+[0]*4)[:4]
                enemies[i,-8:-4] /= 40
                enemies[i,-4:] = catalogs(self.wide)[1].get(species, (0,0,0,0))
        row["instances"] = np.concatenate((row["instances"], cards), axis=1)
        row["enemies"] = np.concatenate((row["enemies"], enemies), axis=1)
        row["player"] = np.concatenate((row["player"], player))
        return row


def extend(net):
    # Insert zero-initialized columns exactly where the encoder concatenates the extra inputs.
    for layer, offset, count in ((net.encoder.card, 24+CARD_FEATURES, CARD_WIDTH),
                                  (net.encoder.player, PLAYER_FEATURES, PLAYER_WIDTH),
                                  (net.encoder.enemy, ENEMY_FEATURES, ENEMY_WIDTH)):
        old = layer[0]
        new = nn.Linear(old.in_features+count, old.out_features)
        with torch.no_grad():
            new.weight.zero_()
            new.weight[:,:offset].copy_(old.weight[:,:offset])
            new.weight[:,offset+count:].copy_(old.weight[:,offset:])
            new.bias.copy_(old.bias)
        layer[0] = new
    return net
