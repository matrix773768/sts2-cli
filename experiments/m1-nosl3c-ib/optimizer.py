"""Bounded microbatch updates with unchanged per-trajectory weights."""
import math
import statistics
from time import perf_counter, process_time

import torch
from torch.nn.functional import binary_cross_entropy

from batched import forward
from features import FastDecision, protocol
from nosl_experience import targets
from nosl_model import Decision, WIDTH, checkpoint


class Times:
    def __init__(self):
        self.wall, self.cpu = {}, {}

    def start(self):
        return perf_counter(), process_time()

    def end(self, name, tick):
        self.wall[name] = self.wall.get(name, 0.) + perf_counter() - tick[0]
        self.cpu[name] = self.cpu.get(name, 0.) + process_time() - tick[1]


def prepare(rows, decision_type, times):
    tick = times.start()
    staged = []
    for row in rows:
        decisions, indexes, behavior = [], [], []
        for step in row["transitions"]:
            d = decision_type(step["observation"])
            i = step["action"]["index"]
            if d.actions[i] != step["action"] or not step["advanced"]:
                raise ValueError("Invalid chosen action in qualified trajectory")
            decisions.append(d)
            indexes.append(i)
            behavior.append(step["behavior_logp"])
        if not decisions:
            raise ValueError("Terminal feedback has no decisions")
        w, hp, _ = targets(row["feedback"])
        staged.append((decisions, torch.tensor(indexes), torch.tensor(behavior), w, hp))
    times.end("features", tick)
    return staged


def roll_scalar(policy, item, cfg, times, witness):
    decisions, indexes, recorded, won, hp = item
    utility = won + cfg["hp_weight"] * hp
    memory = torch.zeros(WIDTH)
    actor, critic, entropy, advantages, errors = [], [], [], [], []
    for d, chosen, behavior in zip(decisions, indexes, recorded, strict=True):
        tick = times.start()
        logits, value, state, actions = policy(d, memory)
        times.end("forward_logits", tick)
        tick = times.start()
        logp = logits.log_softmax(0)
        v = value.detach()
        a = utility - v[0] - cfg["hp_weight"] * v[1]
        actor.append(-logp[chosen] * a)
        critic.append(binary_cross_entropy(value[0], value.new_tensor(won)) + (value[1] - hp).square())
        entropy.append(-(logp.exp() * logp).sum())
        advantages.append(a)
        errors.append((logp[chosen].detach() - behavior).abs())
        if witness is not None:
            witness.append((value.detach().clone(), logp.detach().clone()))
        times.end("loss_graph", tick)
        tick = times.start()
        memory = policy.remember(memory, state, actions[chosen])
        times.end("history_gru", tick)
    return (torch.stack((torch.stack(actor).sum(), torch.stack(critic).mean(), torch.stack(entropy).sum())),
            torch.stack(advantages).mean()[None], torch.stack(errors).max())


def roll_batched(policy, staged, cfg, times, witness):
    # Decreasing lengths leave the active states as a prefix at each step.
    staged = sorted(staged, key=lambda x: len(x[0]), reverse=True)
    lengths = torch.tensor([len(item[0]) for item in staged])
    w = torch.tensor([item[3] for item in staged])
    hp = torch.tensor([item[4] for item in staged])
    utility = w + cfg["hp_weight"] * hp
    memory = torch.zeros((len(staged), WIDTH))
    losses, advantages, errors = [], [], []
    for t in range(int(lengths.max())):
        active = [j for j, item in enumerate(staged) if len(item[0]) > t]
        chosen = torch.stack([staged[j][1][t] for j in active])
        recorded = torch.stack([staged[j][2][t] for j in active])
        tick = times.start()
        d = [staged[j][0][t] for j in active]
        logits, value, state, actions, valid = forward(policy, d, memory[:len(active)])
        times.end("forward_logits", tick)
        tick = times.start()
        logp = logits.log_softmax(-1)
        picked = logp.gather(1, chosen[:, None]).squeeze(1)
        safe = logp.masked_fill(~valid, 0.)
        entropy = -(logp.exp() * safe).sum(1)
        current_action = actions[torch.arange(len(active)), chosen]
        n = len(active)
        weight = lengths[:n]
        detached = value.detach()
        a = utility[:n] - detached[:, 0] - cfg["hp_weight"] * detached[:, 1]
        critic = (binary_cross_entropy(value[:, 0], w[:n], reduction="none") +
                  (value[:, 1] - hp[:n]).square()) / weight
        losses.append(torch.stack(((-picked * a).sum(), critic.sum(), entropy.sum())))
        advantages.append(a / weight)
        errors.append((picked.detach() - recorded).abs().max())
        if witness is not None:
            for j in range(n):
                witness.append((value[j].detach().clone(), logp[j, :len(d[j].actions)].detach().clone()))
        times.end("loss_graph", tick)
        tick = times.start()
        memory = policy.history(torch.cat((state, current_action), dim=1), memory[:n])
        times.end("history_gru", tick)
    advantage = sum((torch.nn.functional.pad(a, (0, len(staged) - len(a))) for a in advantages))
    return torch.stack(losses).sum(0), advantage, torch.stack(errors).max()


def train(policy, optimizer, episodes, cfg, model_hash, *, mode="batched", microbatch=16, witness=None):
    if mode not in ("micro", "features", "batched") or microbatch < 1:
        raise ValueError("Unknown optimizer mode or invalid microbatch")
    if any(r["mode"] != "sample" or r["split"] != "train" or
           r["behavior"]["model_sha256"] != model_hash or r["model_version"] != protocol.MODEL_VERSION
           for r in episodes):
        raise ValueError("On-policy batch violates lineage")
    good = [r for r in episodes if targets(r["feedback"]) is not None]
    if not good:
        raise ValueError("Cannot update without qualified terminal feedback")
    times = Times()
    begun = times.start()
    before = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    optimizer.zero_grad(set_to_none=True)
    head = tuple(policy.actor.parameters())
    actor_gradient = [torch.zeros_like(p) for p in head]
    totals = torch.zeros(3)
    advantages = []
    errors = []
    decision_type = Decision if mode == "micro" else FastDecision
    for i in range(0, len(good), microbatch):
        staged = prepare(good[i:i+microbatch], decision_type, times)
        if mode == "batched":
            loss, advantage, error = roll_batched(policy, staged, cfg, times, witness)
        else:
            values = [roll_scalar(policy, item, cfg, times, witness) for item in staged]
            loss = torch.stack([v[0] for v in values]).sum(0)
            advantage = torch.cat([v[1] for v in values])
            error = torch.stack([v[2] for v in values]).max()
        loss = loss / len(good)
        a, c, e = loss.unbind()
        if not torch.isfinite(loss).all() or not torch.isfinite(error) or error.item() > 2e-5:
            raise ValueError("Nonfinite loss or stored policy probability failed replay")
        tick = times.start()
        gradients = torch.autograd.grad(a, head, retain_graph=True)
        for total, gradient in zip(actor_gradient, gradients, strict=True):
            total.add_(gradient)
        times.end("actor_diagnostic_grad", tick)
        tick = times.start()
        (a + cfg["critic_weight"] * c - cfg["entropy_weight"] * e).backward()
        times.end("joint_backward", tick)
        totals += loss.detach()
        advantages.extend(advantage.tolist())
        errors.append(error.item())
    tick = times.start()
    if witness is not None and hasattr(witness, "gradients"):
        witness.gradients.update({k: p.grad.detach().clone() for k, p in policy.named_parameters() if p.grad is not None})
    g = torch.nn.utils.clip_grad_norm_(policy.parameters(), cfg["grad_clip"], error_if_nonfinite=True)
    ag = torch.linalg.vector_norm(torch.cat([x.flatten() for x in actor_gradient])).item()
    cg = torch.linalg.vector_norm(torch.cat([p.grad.flatten() for p in policy.critic.parameters()])).item()
    if not all(math.isfinite(x) and x > 0 for x in (ag, cg)):
        raise FloatingPointError("Actor or critic received no training signal")
    times.end("norm_and_clip", tick)
    tick = times.start()
    optimizer.step()
    times.end("adam", tick)
    after = policy.state_dict()
    if not all(torch.isfinite(p).all() for p in after.values()):
        raise FloatingPointError("Nonfinite model after optimizer step")
    for name in ("critic.1.weight", "critic.1.bias"):
        if not torch.equal(before[name][2], after[name][2]):
            raise ValueError("Disabled potion output row was changed")
    a, c, e = totals.tolist()
    return dict(actor_loss=a, critic_loss=c, entropy_sum_per_episode=e, logp_error=max(errors),
                steps=sum(len(r["transitions"]) for r in good), qualified=len(good),
                seconds=perf_counter()-begun[0], cpu_seconds=process_time()-begun[1],
                phases_s=times.wall, phases_cpu_s=times.cpu, total_gradient_before_clip=g.item(),
                actor_gradient=ag, critic_gradient_after_clip=cg,
                parameter_delta=max((after[k] - v).abs().max().item() for k, v in before.items()),
                model_sha256=protocol.digest(checkpoint(policy)),
                advantage=dict(mean=statistics.mean(advantages), deviation=statistics.pstdev(advantages),
                               minimum=min(advantages), maximum=max(advantages),
                               positive=sum(a > 0 for a in advantages)))