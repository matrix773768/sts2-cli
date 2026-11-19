"""Public-history actor and policy-conditioned critic for NOSL."""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import sys

import torch
from torch import nn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2e"))
from semantics import CardInstance, load_catalog

CATALOG = load_catalog()
VERSION = "nosl3a.actor-critic.v1"
VOCAB = 256
WIDTH = 24
KINDS = ("play_card", "play_with_discard", "use_potion", "end_turn")
POWERS = ("STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "VULNERABLE_POWER", "FRAIL_POWER")
INTENTS = ("Attack", "Buff", "Debuff", "Defend", "Heal", "Status", "Summon")
PREVIEWS = ("damage_per_hit", "hits", "block", "draw")
EFFECT_SLOTS = 4


@lru_cache(maxsize=4096)
def token(value):
    if value is None:
        return 0
    return 1 + int.from_bytes(sha256(value.encode()).digest()[:4], "little") % (VOCAB - 1)


def scalar(value, scale=10):
    return [float(value or 0) / scale, float(value is not None)]


def powers(rows):
    lookup = {p["id"]: p["amount"] for p in rows}
    return [lookup.get(name, 0) / 10 for name in POWERS]


@lru_cache(maxsize=2048)
def static(card_id, upgrade):
    spec = CATALOG.encode_card_instance(CardInstance(card_id, upgrade))
    effects = spec["effects"]
    if len(effects) > EFFECT_SLOTS:
        raise ValueError("N2E effect layout requires a new encoder version")
    ids = [token("type:" + spec["type"]) if spec["type"] else 0,
           token("target:" + spec["targeting"]) if spec["targeting"] else 0,
           token("qualification:" + spec["qualification"])]
    numbers = [*scalar(spec["cost"]), *scalar(spec["x_cost"], 1)]
    for i in range(EFFECT_SLOTS):
        if i < len(effects):
            node = effects[i]
            # Include typed arguments, modifiers, triggers, and unsupported reason.
            # Numeric magnitudes are represented separately with presence bits.
            shape = {k: v for k, v in node.items() if not isinstance(v, (int, float))}
            ids.append(token("effect:" + json.dumps(shape, sort_keys=True)))
            numbers.extend([n for key in ("amount", "hits", "count", "duration")
                            for n in scalar(node.get(key) if isinstance(node.get(key), (int, float)) else None)])
            numbers.append(1.)
        else:
            ids.append(0)
            numbers.extend([0.] * 9)
    return ids, numbers


class Decision:
    """Resolve menu-local references before constructing index-free model features."""
    def __init__(self, obs):
        self.groups = [obs[key] for key in ("deck", "hand", "discard", "exhaust")]
        self.cards = [card for group in self.groups for card in group]
        self.actions = obs["actions"]
        hand = {card["index"]: i + len(self.groups[0]) + 1 for i, card in enumerate(self.groups[1])}
        enemies = {e["index"]: i + 1 for i, e in enumerate(obs["enemies"])}
        self.refs = torch.tensor([[hand[a["card"]] if a["card"] is not None else 0,
                                   hand[a["choice"]] if a["choice"] is not None else 0,
                                   enemies[a["target"]] if a["target"] is not None else 0]
                                  for a in self.actions], dtype=torch.long)
        self.kind = torch.tensor([KINDS.index(a["kind"]) for a in self.actions])
        self.pots = torch.tensor([token(obs["potions"][a["potion"]]) if a["potion"] is not None else 0
                                  for a in self.actions])
        self.preview = torch.tensor([[n for k in PREVIEWS for n in scalar((a["preview"] or {}).get(k))]
                                     for a in self.actions])
        self.action_cost = torch.tensor([scalar(a["cost"]) for a in self.actions])
        self.playable = torch.tensor([float(any(a["card"] == c["index"] for a in self.actions))
                                      for c in self.groups[1]])
        self.energy = obs["energy"]
        self.enemy = torch.tensor([[e["hp"] / 40, e["block"] / 20, sum(e["attack_hits"]) / 30,
                                    len(e["attack_hits"]) / 8, *powers(e["powers"]),
                                    *(float(i in e["intents"]) for i in INTENTS)]
                                   for e in obs["enemies"]], dtype=torch.float32).reshape(-1, 9 + len(INTENTS))
        self.relics = torch.tensor([token(r) for r in obs["relics"]], dtype=torch.long)
        self.inventory = torch.tensor([token(p) for p in obs["potions"]], dtype=torch.long)
        self.player = torch.tensor([obs["hp"] / obs["max_hp"], obs["max_hp"] / 100, obs["block"] / 30,
                                    self.energy / 5, obs["turn"] / 15, obs["draw_count"] / 20,
                                    len(obs["potions"]) / 5, *powers(obs["powers"]),
                                    # Only count is observed for the draw pile.
                                    0.])
        self.card_ids = torch.tensor([token(c["id"]) for c in self.cards], dtype=torch.long)
        self.instance_ids = torch.tensor([[token(c["enchantment"]), token(c["affliction"])]
                                          for c in self.cards], dtype=torch.long).reshape(-1, 2)
        self.instance = torch.tensor([[c["upgrade"] / 2, *scalar(c["cost"]),
                                       *scalar(c["enchantment_amount"]), *scalar(c["affliction_amount"])]
                                      for c in self.cards], dtype=torch.float32).reshape(-1, 7)
        rules = [static(c["id"], c["upgrade"]) for c in self.cards]
        self.rule_ids = torch.tensor([r[0] for r in rules], dtype=torch.long).reshape(-1, 3 + EFFECT_SLOTS)
        self.rule_values = torch.tensor([r[1] for r in rules], dtype=torch.float32).reshape(-1, 4 + 9 * EFFECT_SLOTS)


def mlp(inputs, outputs=WIDTH):
    return nn.Sequential(nn.Linear(inputs, WIDTH), nn.Tanh(), nn.Linear(WIDTH, outputs), nn.Tanh())


def pooled(rows):
    return rows.sum(dim=0) / max(1, len(rows)) ** 0.5


class Policy(nn.Module):
    def __init__(self, mechanics=True, relations=True):
        super().__init__()
        self.mechanics = mechanics
        self.relations = relations
        self.ids = nn.Embedding(VOCAB, 8, padding_idx=0)
        self.rules = nn.Embedding(VOCAB, 4, padding_idx=0)
        mech_dim = 4 * (3 + EFFECT_SLOTS) + 4 + 9 * EFFECT_SLOTS
        self.card = mlp(8 + 16 + 7 + mech_dim)
        self.enemy = mlp(9 + len(INTENTS))
        self.state = mlp(6 * WIDTH + 13 + 16)
        self.action = mlp(3 * WIDTH + 4 + 8 + 2 + 8)
        self.relation = mlp(3 * WIDTH + 4)
        self.actor = nn.Sequential(mlp(3 * WIDTH), nn.Linear(WIDTH, 1))
        self.critic = nn.Sequential(mlp(WIDTH), nn.Linear(WIDTH, 3))
        self.history = nn.GRUCell(2 * WIDTH, WIDTH)

    def forward(self, d, history):
        identity = self.ids(d.card_ids)
        instance_ids = self.ids(d.instance_ids).flatten(1)
        rules = torch.cat((self.rules(d.rule_ids).flatten(1), d.rule_values), dim=1)
        if not self.mechanics:
            rules = torch.zeros_like(rules)
        cards = self.card(torch.cat((identity, instance_ids, d.instance, rules), dim=1))
        groups = cards.split([len(g) for g in d.groups])
        enemies = self.enemy(d.enemy)
        state = self.state(torch.cat([*(pooled(rows) for rows in groups), pooled(enemies), history,
                                      d.player, pooled(self.ids(d.inventory)), pooled(self.ids(d.relics))]))
        c, discard, enemy = d.refs.T
        card_rows = torch.cat((state.new_zeros((1, WIDTH)), cards))
        enemy_rows = torch.cat((state.new_zeros((1, WIDTH)), enemies))
        actions = self.action(torch.cat((card_rows[c], card_rows[discard], enemy_rows[enemy],
                                         nn.functional.one_hot(d.kind, len(KINDS)), self.ids(d.pots),
                                         d.action_cost, d.preview if self.mechanics else torch.zeros_like(d.preview)), dim=1))
        repeated = state.expand(len(actions), -1)
        relations = actions.new_zeros(actions.shape)
        if self.relations and len(groups[1]):
            relations = self.pair_context(d, repeated, actions, groups[1], c)
        logits = self.actor(torch.cat((repeated, actions, relations), dim=1)).squeeze(-1)
        value = self.critic(state).sigmoid()
        return logits, torch.cat((value[:1], value[:1] * value[1:])), state, actions

    def pair_context(self, d, state, actions, hand, chosen):
        n, h = len(actions), len(hand)
        other = d.instance[len(d.groups[0]):len(d.groups[0]) + h, 1:3]
        cost, known = d.action_cost.T
        slack = d.energy / 10 - cost[:, None] - other[:, 0]
        features = torch.stack((slack, known[:, None] * other[:, 1], d.playable.expand(n, h),
                                other[:, 0].expand(n, h)), dim=-1)
        pair = self.relation(torch.cat((actions[:, None, :].expand(n, h, WIDTH),
                                        hand.expand(n, h, WIDTH), state[:, None, :].expand(n, h, WIDTH),
                                        features), dim=-1))
        slots = torch.arange(h) + len(d.groups[0]) + 1
        mask = chosen[:, None] != slots
        return (pair * mask[..., None]).sum(dim=1) / mask.sum(dim=1).clamp_min(1).sqrt()[:, None]

    def remember(self, history, state, action):
        return self.history(torch.cat((state, action)), history)


def checkpoint(model):
    return {"version": VERSION, "catalog": CATALOG.content_sha256,
            "mechanics": model.mechanics, "relations": model.relations,
            "weights": {name: tensor.tolist() for name, tensor in model.state_dict().items()}}


def restore(payload):
    if (payload["version"], payload["catalog"]) != (VERSION, CATALOG.content_sha256):
        raise ValueError("Incompatible model or N2E catalog")
    model = Policy(payload["mechanics"], payload["relations"])
    model.load_state_dict({k: torch.tensor(v) for k, v in payload["weights"].items()})
    return model.eval()
