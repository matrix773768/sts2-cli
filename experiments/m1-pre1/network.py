"""Mechanism-aware Ironclad NOSL encoder and direct legal action policy."""
import torch
from torch import nn
from torch.nn import functional as F

from features import (
    ACTION_FEATURES, CARD_FEATURES, ENEMY_FEATURES, HISTORY, MOD_BUCKETS,
    PLAYER_FEATURES, ZONES, static_table,
)

from labels import DELTA_WIDTH, OUTCOME_WIDTH

VERSION = "sts2.pre1.ironclad.public.v1"


def mlp(input_width, width, output_width):
    return nn.Sequential(nn.Linear(input_width, width), nn.GELU(), nn.Linear(width, output_width))


def slots(tensor, indices):
    return tensor.gather(1, indices.unsqueeze(-1).expand(-1, -1, tensor.size(-1)))


class SharedEncoder(nn.Module):
    def __init__(self, vocabulary, width=96):
        super().__init__()
        self.width = width
        self.register_buffer("mechanics", torch.from_numpy(static_table(vocabulary)), persistent=False)
        self.identity = nn.Embedding(len(vocabulary)+2, 24, padding_idx=0)
        self.symbols = nn.Embedding(MOD_BUCKETS, 8, padding_idx=0)
        self.card = mlp(24+16+CARD_FEATURES+self.mechanics.size(-1), width, width)
        self.enemy = mlp(ENEMY_FEATURES, width, width)
        self.player = mlp(PLAYER_FEATURES+24, width, width)
        self.memory = mlp(3*HISTORY, width, width)
        self.zone = nn.Parameter(torch.empty(len(ZONES)+3, width))
        nn.init.normal_(self.zone, std=.02)
        self.interactions = nn.ModuleList(nn.TransformerEncoderLayer(
            width, 4, dim_feedforward=width*2, dropout=0, batch_first=True, norm_first=True
        ) for _ in range(2))
        self.action = mlp(width*3+ACTION_FEATURES, width, width)
        self.condition = mlp(width*2, width, width)

    def forward(self, batch):
        identities = batch["cards"].long()
        instances = batch["instances"].float()
        mechanics = self.mechanics[identities, instances[:, :, 0].long()]
        card = self.card(torch.cat((self.identity(identities), instances,
                                   self.symbols(batch["mods"].long()).flatten(2), mechanics), -1))
        card = card * identities.ne(0).unsqueeze(-1)
        zone_members = (batch["zones"][:, None, :] ==
                        torch.arange(1, len(ZONES)+1, device=card.device)[None, :, None]).to(card.dtype)
        groups = (zone_members @ card) / zone_members.sum(-1, keepdim=True).clamp_min(1).sqrt()
        enemy_mask = batch["enemies"][:, :, 0].gt(0).unsqueeze(-1)
        enemy = self.enemy(batch["enemies"].float()) * enemy_mask
        enemy_group = enemy.sum(1) / enemy_mask.sum(1).clamp_min(1).sqrt()
        player = self.player(torch.cat((batch["player"].float(),
                                       self.symbols(batch["choice"].long()).flatten(1)), -1))
        memory = self.memory(batch["history"].float().flatten(1))
        context = torch.cat((player[:, None], groups, enemy_group[:, None], memory[:, None]), 1)
        context = context + self.zone
        for layer in self.interactions:
            context = layer(context)
        state = context[:, 0]
        first, second, target = batch["refs"].long().unbind(-1)
        actions = self.action(torch.cat((slots(card, first), slots(card, second),
                                         slots(enemy, target), batch["actions"].float()), -1))
        contextual = self.condition(torch.cat((actions, state[:, None].expand_as(actions)), -1))
        return state, contextual


class Network(nn.Module):
    def __init__(self, vocabulary, width=96):
        super().__init__()
        self.encoder = SharedEncoder(vocabulary, width)
        self.actor = nn.Linear(width, 1)
        self.transition = nn.Linear(width, DELTA_WIDTH)
        self.outcome = mlp(width+2, width, OUTCOME_WIDTH)
        self.order = mlp(width*3, width, 1)

    def forward(self, batch, aux=False):
        state, actions = self.encoder(batch)
        logits = self.actor(actions).squeeze(-1)
        logits = logits.masked_fill(~batch["mask"], -torch.inf)
        if not aux:
            return logits
        chosen = slots(actions, batch["chosen"][:, None].long()).squeeze(1)
        pair = slots(actions, batch["pair"].long())
        first, second = pair.unbind(1)
        forward = self.order(torch.cat((state, first, second), -1))
        backward = self.order(torch.cat((state, second, first), -1))
        return (logits, self.transition(chosen), self.outcome(torch.cat((state, F.one_hot(
            batch["source"].long(), num_classes=2).to(state.dtype)), -1)),
                (forward-backward).squeeze(-1))
