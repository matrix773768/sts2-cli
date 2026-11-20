"""Time-major execution of the frozen policy with explicit zone/menu masks."""
import torch
from torch.nn.functional import one_hot
from torch.nn.utils.rnn import pad_sequence

from nosl_model import KINDS, WIDTH


def gather(rows, indices):
    return rows[torch.arange(len(rows))[:, None], indices]


def forward(policy, decisions, memory):
    def pad(name):
        return pad_sequence([getattr(d, name) for d in decisions], batch_first=True)

    rules = torch.cat((policy.rules(pad("rule_ids")).flatten(2), pad("rule_values")), dim=2)
    if not policy.mechanics:
        rules = torch.zeros_like(rules)
    instance = pad("instance")
    cards = policy.card(torch.cat((policy.ids(pad("card_ids")), policy.ids(pad("instance_ids")).flatten(2),
                                  instance, rules), dim=2))
    sizes = torch.tensor([[len(g) for g in d.groups] for d in decisions])
    ends = sizes.cumsum(1)
    slots = torch.arange(cards.shape[1])[None, None, :]
    masks = (slots >= (ends - sizes)[:, :, None]) & (slots < ends[:, :, None])
    groups = (cards.unsqueeze(1) * masks.unsqueeze(-1)).sum(dim=2) / sizes.clamp_min(1).sqrt().unsqueeze(-1)
    enemies = policy.enemy(pad("enemy"))
    enemy_sizes = torch.tensor([len(d.enemy) for d in decisions])
    enemy_mask = torch.arange(enemies.shape[1]) < enemy_sizes[:, None]
    enemy_pool = (enemies * enemy_mask.unsqueeze(-1)).sum(1) / enemy_sizes.clamp_min(1).sqrt()[:, None]
    inventory = policy.ids(pad("inventory")).sum(1) / torch.tensor(
        [max(1, len(d.inventory)) ** .5 for d in decisions])[:, None]
    relics = policy.ids(pad("relics")).sum(1) / torch.tensor(
        [max(1, len(d.relics)) ** .5 for d in decisions])[:, None]
    state = policy.state(torch.cat((groups.flatten(1), enemy_pool, memory,
                                    torch.stack([d.player for d in decisions]), inventory, relics), dim=1))

    c, discard, enemy = pad("refs").unbind(-1)
    zero = state.new_zeros((len(state), 1, WIDTH))
    card_rows = torch.cat((zero, cards), dim=1)
    enemy_rows = torch.cat((zero, enemies), dim=1)
    costs, preview = pad("action_cost"), pad("preview")
    actions = policy.action(torch.cat((gather(card_rows, c), gather(card_rows, discard), gather(enemy_rows, enemy),
                                       one_hot(pad("kind"), len(KINDS)), policy.ids(pad("pots")), costs,
                                       preview if policy.mechanics else torch.zeros_like(preview),
                                       pad("action_resources")), dim=2))
    repeated = state[:, None, :].expand_as(actions)
    relations = torch.zeros_like(actions)
    hands = int(sizes[:, 1].max())
    if policy.relations and hands:
        # Clip padded indices to an available card. The hand mask removes their contributions.
        hand_idx = sizes[:, :1] + torch.arange(hands)[None, :]
        present = torch.arange(hands)[None, :] < sizes[:, 1:2]
        safe = hand_idx.clamp_max(cards.shape[1] - 1)
        h = gather(cards, safe)
        other = gather(instance, safe)[..., 1:3]
        cost, known = costs.unbind(-1)
        energy = torch.tensor([d.energy / 10 for d in decisions])
        slack = energy[:, None, None] - cost[:, :, None] - other[:, None, :, 0]
        playable = pad("playable")[:, None, :].expand_as(slack)
        features = torch.stack((slack, known[:, :, None] * other[:, None, :, 1], playable,
                                other[:, None, :, 0].expand_as(slack)), dim=-1)
        n = actions.shape[1]
        pair = policy.relation(torch.cat((actions[:, :, None, :].expand(-1, -1, hands, -1),
                                         h[:, None, :, :].expand(-1, n, -1, -1),
                                         repeated[:, :, None, :].expand(-1, -1, hands, -1), features), dim=-1))
        mask = present[:, None, :] & (c[:, :, None] != hand_idx[:, None, :] + 1)
        relations = (pair * mask.unsqueeze(-1)).sum(2) / mask.sum(2).clamp_min(1).sqrt().unsqueeze(-1)
    logits = policy.actor(torch.cat((repeated, actions, relations), dim=2)).squeeze(-1)
    valid = torch.arange(logits.shape[1]) < torch.tensor([len(d.actions) for d in decisions])[:, None]
    value = policy.return_head(state).squeeze(-1)
    return logits.masked_fill(~valid, -torch.inf), value, state, actions, valid
