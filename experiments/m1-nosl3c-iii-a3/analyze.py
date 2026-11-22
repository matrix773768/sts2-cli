"""Decompose frozen v4 gradients without applying an optimizer step."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean, pstdev
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii-a2"))
from curve import a1, digest, load_step, p0, read, save, torch, v4

TRAINING = v4.optimize.__globals__
STEPS = (1, 12, 36, 60, 84)
TERMS = ("actor", "critic_weighted", "entropy_weighted")


def fixtures(directory, step):
    database = directory / "training/training.sqlite"
    before, stamp = load_step(database, step - 1)
    after, post_stamp = load_step(database, step)
    rows = []
    with a1.readonly(database) as db:
        query = ("SELECT root,rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                 "WHERE phase='train' AND step=? ORDER BY root")
        for key, raw, checksum in db.execute(query, (step - 1,)):
            assert sha256(raw).hexdigest() == checksum
            batch = p0["unpack"](raw)
            audit = read(directory / "training/audit" / f"{step-1:06d}-{key}.json")
            assert digest(audit) == batch["evidence_sha256"]
            for row in batch["rows"]:
                if row["feedback"]["eligible"]:
                    assert batch["status"] == "admissible_" + row["feedback"]["status"]
                    assert audit["terminal_verified"] and audit["native_terminal_stamp"]
                    rows.append(row)
    return before, after, stamp, post_stamp, rows


def clone_grads(parameters):
    return [torch.zeros_like(p) if p.grad is None else p.grad.detach().clone() for p in parameters]


class NoStep:
    """Expose the optimizer interface used by v4, without applying updates."""
    def __init__(self, policy):
        self.policy = policy

    def zero_grad(self, *, set_to_none):
        self.policy.zero_grad(set_to_none=set_to_none)

    def step(self):
        pass


def original_gradients(policy, rows, cfg, model_hash):
    parameters = list(policy.parameters())
    clip = torch.nn.utils.clip_grad_norm_
    measured = {}

    def capture(args, *rest, **kwargs):
        measured["raw"] = clone_grads(parameters)
        norm = clip(args, *rest, **kwargs)
        measured["clipped"] = clone_grads(parameters)
        return norm

    with patch.object(torch.nn.utils, "clip_grad_norm_", capture):
        stats = v4.optimize(policy, NoStep(policy), rows, cfg, model_hash)
    assert stats["model_sha256"] == model_hash
    return stats, measured["raw"], measured["clipped"]


def stats(xs):
    return dict(n=len(xs), mean=mean(xs), sd=pstdev(xs), min=min(xs), max=max(xs)) if xs else {"n": 0}


def decompose(policy, rows, cfg, *, decoded_critic_loss=False):
    scale = cfg.get("a5", {}).get("value_scale", 1)
    objective = v4.Objective(**cfg["objective"])
    prepared = [(row["transitions"], objective.reward(row["feedback"], row["hp_accounting"]["initial_hp"]),
                 row["feedback"]["status"]) for row in rows]
    params = tuple(policy.parameters())
    totals = {term: [torch.zeros_like(p) for p in params] for term in TERMS}
    scalar = Counter()
    cases = {status: dict(returns=[], first_values=[], values=[], error=[]) for status in ("predicted_win", "death")}
    for _, reward, status in prepared:
        cases[status]["returns"].append(reward)
    hidden, saturated = 0, 0

    def observe_output(_module, inputs):
        nonlocal hidden, saturated
        activation = inputs[0].detach()
        hidden += activation.numel()
        saturated += (activation.abs() > .99).sum().item()

    with policy.return_head[-1].register_forward_pre_hook(observe_output):
        for start in range(0, len(prepared), cfg["microbatch"]):
            group = sorted(prepared[start:start + cfg["microbatch"]], key=lambda p: -len(p[0]))
            history = torch.zeros(len(group), TRAINING["WIDTH"])
            terms = {term: [] for term in TERMS}
            for t in range(len(group[0][0])):
                active = [(route, r, status) for route, r, status in group if t < len(route)]
                steps = [route[t] for route, _, _ in active]
                decisions = [TRAINING["decision"](json.dumps(step["observation"], sort_keys=True)) for step in steps]
                idx = torch.tensor([step["action"]["index"] for step in steps])
                logits, value, state, actions, mask = TRAINING["forward"](policy, decisions, history[:len(active)])
                logp = logits.log_softmax(-1)
                batch = torch.arange(len(active))
                chosen = logp[batch, idx]
                reward = value.new_tensor([r for _, r, _ in active])
                actor = -(chosen * (reward - scale * value.detach())).sum()
                error = scale * value - reward if decoded_critic_loss else value - reward / scale
                critic = (error.square() / value.new_tensor([len(route) for route, _, _ in active])).sum()
                entropy = -(logp.exp() * logp.masked_fill(~mask, 0)).sum()
                scalar.update(actor_loss=actor.item(), critic_loss=critic.item(), entropy=entropy.item())
                terms["actor"].append(actor)
                terms["critic_weighted"].append(cfg["critic_weight"] * critic)
                terms["entropy_weighted"].append(-cfg["entropy_weight"] * entropy)
                for (_, r, status), prediction in zip(active, (scale * value.detach()).tolist(), strict=True):
                    case = cases[status]
                    case["values"].append(prediction)
                    case["error"].append(prediction - r)
                    if t == 0:
                        case["first_values"].append(prediction)
                history = policy.history(torch.cat((state, actions[batch, idx]), dim=1), history[:len(active)])
            for i, term in enumerate(TERMS):
                loss = torch.stack(terms[term]).sum() / len(prepared)
                grads = torch.autograd.grad(loss, params, retain_graph=i < len(TERMS)-1, allow_unused=True)
                for total, grad in zip(totals[term], grads, strict=True):
                    if grad is not None:
                        total.add_(grad.detach())
    outcome = {status: {key: stats(xs) for key, xs in group.items()} |
               dict(mae=mean(map(abs, group["error"])) if group["error"] else None)
               for status, group in cases.items()}
    outcome["return_hidden_abs_gt_099"] = saturated / hidden
    return totals, scalar, outcome


def flat(gradients, indices):
    return torch.cat([gradients[i].reshape(-1).double() for i in indices])


def norm(tensor):
    return torch.linalg.vector_norm(tensor).item()


def measure(directory, step, cfg):
    before, after, pre_stamp, post_stamp, rows = fixtures(directory, step)
    policy = v4.Policy().eval()
    policy.load_state_dict(before["model"])
    model_hash = digest(v4.checkpoint_policy(policy))
    assert model_hash == before["model_sha256"]
    hist = read(directory / "training" / f"metrics-{step:02d}.json")["stats"]
    assert after["model_sha256"] == hist["model_sha256"]
    original, raw, clipped = original_gradients(policy, rows, cfg, model_hash)
    for key in ("actor_loss", "critic_loss", "entropy", "decisions", "qualified", "logp_error", "grad_norm"):
        assert original[key] == hist[key], (step, key, original[key], hist[key])
    pieces, scalars, outcomes = decompose(policy, rows, cfg)
    assert all(scalars[key] == original[key] for key in scalars)
    assert digest(v4.checkpoint_policy(policy)) == model_hash
    names = [name for name, _ in policy.named_parameters()]
    delta = [after["model"][name] - before["model"][name] for name in names]
    indices = {
        "all": list(range(len(names))),
        "actor_head": [i for i, name in enumerate(names) if name.startswith("actor.")],
        "critic_head": [i for i, name in enumerate(names) if name.startswith("return_head.")],
        "state": [i for i, name in enumerate(names) if name.startswith("state.")],
        "shared": [i for i, name in enumerate(names) if not name.startswith(("actor.", "return_head.", "relation."))],
    }
    norms, cosine = {}, {}
    for key, group in indices.items():
        vectors = {term: flat(grad, group) for term, grad in pieces.items()}
        original_vector = flat(raw, group)
        combined = sum(vectors.values())
        norms[key] = {term: norm(value) for term, value in vectors.items()} | dict(
            reconstructed=norm(combined), original=norm(original_vector), clipped=norm(flat(clipped, group)),
            residual=norm(combined-original_vector), adam_delta=norm(flat(delta, group)))
        if key in ("shared", "state"):
            actor, critic = vectors["actor"], vectors["critic_weighted"]
            cosine[key] = torch.dot(actor, critic).item() / (norm(actor) * norm(critic))
    assert norms["all"]["residual"] / original["grad_norm"] < 1e-5
    clip_factor = min(1, cfg["grad_clip"] / (original["grad_norm"] + 1e-6))
    output = policy.return_head[-1]
    scale = cfg.get("a5", {}).get("value_scale", 1)
    weight = output.weight.detach()
    bias = output.bias.detach().item()
    return dict(step=step, rows=len(rows), snapshots=[pre_stamp, post_stamp],
                historical_norm=hist["grad_norm"], decisions=hist["decisions"], norms=norms,
                cosine=cosine, clip_factor=clip_factor, outcome=outcomes,
                critic_output=dict(bias=bias, weight_l1=weight.abs().sum().item(),
                                   upper_abs_bound=scale*(abs(bias)+weight.abs().sum().item()),
                                   bias_delta=(after["model"]["return_head.2.bias"] -
                                               before["model"]["return_head.2.bias"]).item(),
                                   weight_delta_l2=norm(after["model"]["return_head.2.weight"] - weight)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a2", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cfg = read(args.a2 / "protocol.json")["config"]
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    output = args.output.resolve()
    output.mkdir(parents=True)
    records = []
    for step in STEPS:
        records.append(measure(args.a2, step, cfg))
        save(output / "gradient-diagnosis.json", dict(config=cfg, batches=records))
        print(f"Verified update {step}", flush=True)


if __name__ == "__main__":
    main()
