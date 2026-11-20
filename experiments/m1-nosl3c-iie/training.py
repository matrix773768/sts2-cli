"""Signed Monte Carlo returns with masked time-major v4 optimization."""
from collections import Counter
from functools import lru_cache
import json

import torch
from torch import nn

from terminal_contract import targets
from batched import forward
from objective import Objective
from nosl_experience import digest
from nosl_model import WIDTH, checkpoint

MODEL = "nosl3c.hp-loss-actor-critic.v4"


class Policy(targets.base.Policy):
    def __init__(self):
        super().__init__()
        del self.critic
        self.return_head = nn.Sequential(nn.Linear(WIDTH, WIDTH), nn.Tanh(), nn.Linear(WIDTH, 1))

    def forward(self, decision, history):
        logits, values, state, actions, _ = forward(self, [decision], history.unsqueeze(0))
        return logits[0], values[0], state[0], actions[0]


def checkpoint_policy(policy):
    return checkpoint(policy) | {"version": MODEL, "observation": targets.base.OBSERVATION}


@lru_cache(maxsize=2048)
def decision(encoded):
    return targets.Decision(json.loads(encoded))


def optimize(policy, optimizer, rows, config, model_hash):
    objective = Objective(**config["objective"])
    prepared = []
    for row in rows:
        if (row["behavior"]["model_sha256"] != model_hash or row["model_version"] != MODEL
                or row["feedback"]["evidence"] != "exact_native_route" or row["mode"] != "sample"
                or row["split"] != "train"):
            raise ValueError("Invalid on-policy certification lineage")
        reward = objective.reward(row["feedback"], row["hp_accounting"]["initial_hp"])
        if reward is None or not row["transitions"]:
            raise ValueError("Missing certified reward or decisions")
        prepared.append((row["transitions"], reward))
    optimizer.zero_grad(set_to_none=True)
    totals = Counter()
    max_error = 0.
    for start in range(0, len(prepared), config["microbatch"]):
        group = sorted(prepared[start:start + config["microbatch"]], key=lambda p: -len(p[0]))
        history = torch.zeros(len(group), WIDTH)
        terms = []
        for t in range(len(group[0][0])):
            active = [(steps, reward) for steps, reward in group if t < len(steps)]
            n = len(active)
            steps = [route[t] for route, _ in active]
            decisions = [decision(json.dumps(s["observation"], sort_keys=True)) for s in steps]
            idx = torch.tensor([s["action"]["index"] for s in steps])
            if any(d.actions[i] != s["action"] or not s["advanced"]
                   for d, i, s in zip(decisions, idx, steps, strict=True)):
                raise ValueError("Uncommitted or mismatched action")
            logits, value, state, actions, mask = forward(policy, decisions, history[:n])
            logp = logits.log_softmax(-1)
            batch = torch.arange(n)
            chosen = logp[batch, idx]
            reference = torch.tensor([s["behavior_logp"] for s in steps])
            error = (chosen.detach() - reference).abs().max().item()
            max_error = max(max_error, error)
            if error > 2e-5:
                raise ValueError(f"Behavior replay mismatch {error}")
            reward = value.new_tensor([payoff for _, payoff in active])
            advantage = reward - value.detach()
            actor = -(chosen * advantage).sum()
            critic = ((value - reward).square() / value.new_tensor([len(p) for p, _ in active])).sum()
            entropy = -(logp.exp() * logp.masked_fill(~mask, 0)).sum()
            terms.append(actor + config["critic_weight"] * critic - config["entropy_weight"] * entropy)
            history = policy.history(torch.cat((state, actions[batch, idx]), dim=1), history[:n])
            totals.update(actor_loss=actor.item(), critic_loss=critic.item(), entropy=entropy.item(), decisions=n)
        (torch.stack(terms).sum() / len(prepared)).backward()
    norm = torch.nn.utils.clip_grad_norm_(policy.parameters(), config["grad_clip"], error_if_nonfinite=True)
    optimizer.step()
    if not all(torch.isfinite(p).all() for p in policy.parameters()):
        raise FloatingPointError("Nonfinite v4 policy")
    return dict(totals, logp_error=max_error, qualified=len(prepared), grad_norm=norm.item(),
                return_min=min(r for _,r in prepared), return_max=max(r for _,r in prepared),
                model_sha256=digest(checkpoint_policy(policy)))
