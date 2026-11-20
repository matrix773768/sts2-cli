"""Frozen NOSL3A actor-critic update with the inactive potion loss excluded."""
import math
import statistics
from time import perf_counter

import torch
from torch.nn.functional import binary_cross_entropy

from protocol import MODEL_VERSION, digest
from nosl_experience import targets
from nosl_model import Decision, WIDTH, checkpoint


def train(policy, optimizer, episodes, config, model_hash):
    good = [r for r in episodes if targets(r["feedback"]) is not None]
    if not good:
        raise ValueError("Cannot update without qualified terminal feedback")
    if any(r["mode"] != "sample" or r["split"] != "train" or
           r["behavior"]["model_sha256"] != model_hash or r["model_version"] != MODEL_VERSION for r in episodes):
        raise ValueError("On-policy batch violates lineage")
    started = perf_counter()
    before = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    optimizer.zero_grad(set_to_none=True)
    actor_gradient = [torch.zeros_like(p) for p in policy.actor.parameters()]
    totals = dict(actor_loss=0., critic_loss=0., entropy_sum_per_episode=0., logp_error=0.)
    advantages = []
    decisions = 0
    for row in good:
        won, hp, _ = targets(row["feedback"])
        utility = won + config["hp_weight"] * hp
        memory = torch.zeros(WIDTH)
        actor, critic, entropy, episode_adv = [], [], [], []
        for step in row["transitions"]:
            d = Decision(step["observation"])
            logits, value, state, actions = policy(d, memory)
            logp = logits.log_softmax(0)
            chosen = step["action"]["index"]
            if d.actions[chosen] != step["action"] or not step["advanced"]:
                raise ValueError("Invalid chosen action in qualified trajectory")
            error = abs(logp[chosen].item() - step["behavior_logp"])
            totals["logp_error"] = max(error, totals["logp_error"])
            if error > 2e-5:
                raise ValueError("Stored policy probability failed replay")
            v = value.detach()
            a = utility - v[0] - config["hp_weight"] * v[1]
            actor.append(-logp[chosen] * a)
            critic.append(binary_cross_entropy(value[0], value.new_tensor(won)) + (value[1] - hp).square())
            entropy.append(-(logp.exp() * logp).sum())
            episode_adv.append(a.item())
            memory = policy.remember(memory, state, actions[chosen])
        if not actor:
            raise ValueError("Terminal feedback has no decisions")
        a = torch.stack(actor).sum()
        c = torch.stack(critic).mean()
        e = torch.stack(entropy).sum()
        loss = (a + config["critic_weight"] * c - config["entropy_weight"] * e) / len(good)
        if not torch.isfinite(loss):
            raise FloatingPointError("Nonfinite training loss")
        grad = torch.autograd.grad(a, tuple(policy.actor.parameters()), retain_graph=True)
        for total, value in zip(actor_gradient, grad, strict=True):
            total.add_(value / len(good))
        loss.backward()
        totals["actor_loss"] += a.item() / len(good)
        totals["critic_loss"] += c.item() / len(good)
        totals["entropy_sum_per_episode"] += e.item() / len(good)
        advantages.append(statistics.mean(episode_adv))
        decisions += len(actor)
    g = torch.nn.utils.clip_grad_norm_(policy.parameters(), config["grad_clip"], error_if_nonfinite=True)
    actor_norm = torch.linalg.vector_norm(torch.cat([x.flatten() for x in actor_gradient])).item()
    critic_norm = torch.linalg.vector_norm(torch.cat([p.grad.flatten() for p in policy.critic.parameters()])).item()
    if not all(math.isfinite(x) and x > 0 for x in (actor_norm, critic_norm)):
        raise FloatingPointError("Actor or critic received no training signal")
    optimizer.step()
    after = policy.state_dict()
    if not all(torch.isfinite(p).all() for p in after.values()):
        raise FloatingPointError("Nonfinite model after optimizer step")
    for key in ("critic.1.weight", "critic.1.bias"):
        if not torch.equal(before[key][2], after[key][2]):
            raise ValueError("Disabled potion output row was changed")
    payload = checkpoint(policy)
    return dict(**totals, steps=decisions, qualified=len(good), seconds=perf_counter() - started,
                total_gradient_before_clip=g.item(), actor_gradient=actor_norm, critic_gradient_after_clip=critic_norm,
                parameter_delta=max((after[k] - v).abs().max().item() for k, v in before.items()),
                model_sha256=digest(payload),
                advantage=dict(mean=statistics.mean(advantages), deviation=statistics.pstdev(advantages),
                               minimum=min(advantages), maximum=max(advantages),
                               positive=sum(a > 0 for a in advantages)))