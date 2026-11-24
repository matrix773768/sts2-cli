"""Policy-conditioned result distributions over death and victory HP fraction."""
from pathlib import Path

import torch
from torch import nn

from sv_data import FEATURES, PRE1, checksum
from network import SharedEncoder, mlp, slots

VERSION = "sts2.sv3a.value.v1"


class ValueNet(nn.Module):
    def __init__(self, vocabulary, width=96, bins=32, policy_slots=16):
        super().__init__()
        self.encoder = SharedEncoder(vocabulary, width)
        self.policy = nn.Embedding(policy_slots, 12)
        self.v = mlp(width + 12, width, 1 + 2 * bins)
        self.q = mlp(width + 12, width, 1 + 2 * bins)
        self.bins = bins
        self.register_buffer("fractions", torch.linspace(0, 1, bins))

    def forward(self, batch, chosen_only=False):
        features = {key: batch[key] for key in FEATURES}
        if chosen_only:
            for key in ("actions", "refs"):
                features[key] = slots(features[key], batch["chosen"].long()[:, None])
        state, actions = self.encoder(features)
        behavior = self.policy(batch["policy"].long())
        v = self.v(torch.cat((state, behavior), -1))
        q = self.q(torch.cat((actions, behavior[:, None].expand(-1, actions.size(1), -1)), -1))
        if chosen_only:
            q = q[:, 0]
        return v.float(), q.float()

    def split(self, outcome):
        return outcome[..., :self.bins + 1], outcome[..., self.bins + 1:]

    def probabilities(self, outcome):
        return self.split(outcome)[0].softmax(-1)

    def utility(self, probabilities):
        return -probabilities[..., 0] + (probabilities[..., 1:] * (1 + .25 * self.fractions)).sum(-1)

    def expected_hp(self, outcome, current_max):
        logits, max_delta = self.split(outcome)
        probabilities = logits.softmax(-1)[..., 1:]
        max_hp = (current_max[..., None] + 25 * max_delta).clamp_min(1)
        return (probabilities * self.fractions * max_hp).sum(-1)


def model_spec(cfg):
    return dict(width=cfg["width"], bins=cfg["hp_bins"], policy_slots=cfg["policy_slots"])


def contract():
    return {name: checksum(path) for name, path in {
        "pre1_features": PRE1 / "features.py", "pre1_network": PRE1 / "network.py",
        "sv3a_model": Path(__file__),
    }.items()} | {"n2e": checksum(PRE1.parent / "m1-n2e/cards.json")}


def load(path, device="cpu"):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if payload["version"] != VERSION or payload["sources"] != contract():
        raise ValueError("Value checkpoint contract mismatch")
    net = ValueNet(payload["vocabulary"], **payload["spec"])
    net.load_state_dict(payload["model"])
    return net.eval().to(device), payload
