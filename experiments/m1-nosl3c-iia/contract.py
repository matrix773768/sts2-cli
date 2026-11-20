"""Public II-A input and actor-critic adapter; frozen v1 remains independently replayable."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-nosl3a"))
from nosl_experience import public_observation as public_v1
import torch
from torch import nn
from nosl_model import Decision as DecisionV1
from nosl_model import CATALOG, KINDS, Policy as PolicyV1, WIDTH, checkpoint, mlp, pooled

OBSERVATION = "sts2.nosl_observation.v2"
TRANSITION = "sts2.nosl_transition.v2"
MODEL_VERSION = "nosl3c.mechanism-actor-critic.public-zones.v2"
CHOICES = {"play_with_discard": "hand", "play_with_draw_top": "discard"}


def public_observation(wire):
    if wire.get("schema") != OBSERVATION:
        raise ValueError("Unexpected observation version")
    obs = public_v1(wire)
    for action, raw in zip(obs["actions"], wire["actions"], strict=True):
        zone = raw.get("choice_zone")
        expected = CHOICES.get(action["kind"])
        if zone != expected or (zone is None) != (action["choice"] is None):
            raise ValueError("Invalid choice zone")
        if zone is not None and action["choice"] not in {c["index"] for c in obs[zone]}:
            raise ValueError("Choice is outside its public pile")
        action["choice_zone"] = zone
        action["star_cost"] = raw.get("star_cost")
        action["energy_x"] = raw["energy_x"]
        action["star_x"] = raw["star_x"]
    obs["stars"] = wire["stars"]
    obs["schema"] = OBSERVATION
    return obs


class Decision(DecisionV1):
    """Reuse the candidate embedding for each public pile and retain the wire action."""
    def __init__(self, obs):
        if obs.get("schema") != OBSERVATION:
            raise ValueError("Expected v2 public observation")
        normalized = deepcopy(obs)
        for action in normalized["actions"]:
            if action["kind"] == "play_with_draw_top":
                action.update(kind="play_with_discard", choice=None)
        super().__init__(normalized)
        self.actions = obs["actions"]
        discard = {c["index"]: i + len(self.groups[0]) + len(self.groups[1]) + 1
                   for i, c in enumerate(self.groups[2])}
        for i, action in enumerate(self.actions):
            if action["choice_zone"] == "discard":
                self.refs[i, 1] = discard[action["choice"]]

        self.player[-1] = obs["stars"] / 10
        self.action_resources = torch.tensor([
            [(a["star_cost"] or 0) / 10, float(a["energy_x"]), float(a["star_x"]),
             float(a["choice_zone"] == "discard")] for a in self.actions])


class Policy(PolicyV1):
    def __init__(self, mechanics=True, relations=True):
        super().__init__(mechanics, relations)
        self.action = mlp(3 * WIDTH + len(KINDS) + 8 + 2 + 8 + 4)

    @classmethod
    def from_v1(cls, old):
        model = cls(old.mechanics, old.relations)
        weights = old.state_dict()
        weights["action.0.weight"] = nn.functional.pad(weights["action.0.weight"], (0, 4))
        model.load_state_dict(weights)
        return model

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
        card, candidate, enemy = d.refs.T
        card_rows = torch.cat((state.new_zeros((1, WIDTH)), cards))
        enemy_rows = torch.cat((state.new_zeros((1, WIDTH)), enemies))
        preview = d.preview if self.mechanics else torch.zeros_like(d.preview)
        actions = self.action(torch.cat((card_rows[card], card_rows[candidate], enemy_rows[enemy],
                                         nn.functional.one_hot(d.kind, len(KINDS)), self.ids(d.pots),
                                         d.action_cost, preview, d.action_resources), dim=1))
        repeated = state.expand(len(actions), -1)
        relations = actions.new_zeros(actions.shape)
        if self.relations and len(groups[1]):
            relations = self.pair_context(d, repeated, actions, groups[1], card)
        logits = self.actor(torch.cat((repeated, actions, relations), dim=1)).squeeze(-1)
        value = self.critic(state).sigmoid()
        return logits, torch.cat((value[:1], value[:1] * value[1:])), state, actions


def save_policy(model):
    return checkpoint(model) | {"version": MODEL_VERSION, "observation": OBSERVATION}


def restore_policy(payload):
    identity = (payload["version"], payload["observation"], payload["catalog"])
    if identity != (MODEL_VERSION, OBSERVATION, CATALOG.content_sha256):
        raise ValueError("Incompatible II-A policy checkpoint")
    model = Policy(payload["mechanics"], payload["relations"])
    model.load_state_dict({k: torch.tensor(v) for k, v in payload["weights"].items()})
    return model.eval()
