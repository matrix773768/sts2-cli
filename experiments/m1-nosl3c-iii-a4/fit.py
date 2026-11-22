"""Compare two value-head parameterizations on the frozen A2 trajectory bank."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import random
from statistics import median
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii-a2"))
from curve import a1, digest, load_step, p0, read, save, torch, v4

OPS = v4.optimize.__globals__
SCALE = 100
SPLIT_SEED = 73192401
ORDER_SEED = 73192402
LR = 0.001
BATCH = 32
STEPS = (0, 32, 128, 384)
MODEL_HASH = "180b1141d52fe836d5b7770c90c7be193c1c9a8b86bfd7e152274f2e8cd540a6"


def bank(path, objective):
    records = []
    with a1.readonly(path / "training/training.sqlite") as db:
        query = ("SELECT step,root,rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                 "WHERE phase='train' ORDER BY step,root")
        for step, key, raw, stamp in db.execute(query):
            assert sha256(raw).hexdigest() == stamp
            case = p0["unpack"](raw)
            if not case["status"].startswith("admissible_"):
                continue
            row, = case["rows"]
            evidence = read(path / "training/audit" / f"{step:06d}-{key}.json")
            assert digest(evidence) == case["evidence_sha256"]
            assert evidence["terminal_verified"] and evidence["native_terminal_stamp"]
            root = case["spec"]
            fb = row["feedback"]
            assert case["status"] == "admissible_" + fb["status"]
            reward = objective.reward(fb, root["hp"])
            assert reward is not None and row["transitions"]
            records.append(dict(key=f"{step}:{key}", root=digest(root), seed=root["seed"],
                                character=root["character"], act=root["act"], stage=step//21,
                                outcome=fb["status"], reward=reward, route=row["transitions"]))
    assert len(records) == len({r["root"] for r in records}) == len({r["seed"] for r in records}) == 1419
    return records


def split(records):
    rng = random.Random(SPLIT_SEED)
    strata = defaultdict(list)
    for record in records:
        strata[record["stage"], record["outcome"], record["character"], record["act"]].append(record)
    holdout = set()
    # Use a common randomized offset for cumulative proportional allocation
    # within stage/outcome, so even small role/act cells can be represented.
    previous = None
    for label, group in sorted(strata.items()):
        if label[:2] != previous:
            offset = rng.random()
            count = 0
        rng.shuffle(group)
        target = math.floor((count + len(group)) / 5 + offset) - math.floor(count / 5 + offset)
        holdout.update(row["root"] for row in group[:target])
        count += len(group)
        previous = label[:2]
    return ([r for r in records if r["root"] not in holdout],
            [r for r in records if r["root"] in holdout])


def cache_group(policy, records):
    states = [[] for _ in records]
    history = torch.zeros(len(records), OPS["WIDTH"])
    for t in range(len(records[0]["route"])):
        active = [r["route"][t] for r in records if t < len(r["route"])]
        decisions = [OPS["decision"](json.dumps(step["observation"], sort_keys=True)) for step in active]
        positions = torch.tensor([step["action"]["index"] for step in active])
        assert all(step["advanced"] and decision.actions[pos] == step["action"]
                   for decision, pos, step in zip(decisions, positions.tolist(), active, strict=True))
        _, _, state, options, _ = OPS["forward"](policy, decisions, history[:len(active)])
        for i, value in enumerate(state):
            states[i].append(value)
        history = policy.history(torch.cat((state, options[torch.arange(len(active)), positions]), dim=1),
                                 history[:len(active)])
    return [torch.stack(value) for value in states]


@torch.no_grad()
def cache(policy, records):
    states = {}
    for start in range(0, len(records), BATCH):
        group = sorted(records[start:start+BATCH], key=lambda r: -len(r["route"]))
        states.update((r["key"], value) for r, value in zip(group, cache_group(policy, group), strict=True))
    return states


@torch.no_grad()
def direct(policy, records, states):
    max_state = max_value = 0.
    for record in records:
        history = torch.zeros(OPS["WIDTH"])
        values, features = [], []
        for step in record["route"]:
            decision = OPS["decision"](json.dumps(step["observation"], sort_keys=True))
            _, value, state, actions = policy(decision, history)
            values.append(value)
            features.append(state)
            history = policy.remember(history, state, actions[step["action"]["index"]])
        cached = states[record["key"]]
        max_state = max(max_state, (cached - torch.stack(features)).abs().max().item())
        max_value = max(max_value, (policy.return_head(cached).flatten() - torch.stack(values)).abs().max().item())
    assert max_state < 2e-5 and max_value < 2e-5
    return dict(routes=len(records), state_max_abs=max_state, decoded_max_abs=max_value)


def tensors(records, states):
    features = torch.cat([states[r["key"]] for r in records])
    lengths = [len(states[r["key"]]) for r in records]
    roots = torch.arange(len(records)).repeat_interleave(torch.tensor(lengths))
    returns = torch.tensor([r["reward"] for r in records])
    starts = torch.tensor([0, *lengths[:-1]]).cumsum(0)
    return features, roots, returns, torch.tensor(lengths), starts


def optimizer_order(n):
    rng = random.Random(ORDER_SEED)
    order = []
    while len(order) < STEPS[-1]:
        epoch = list(range(n))
        rng.shuffle(epoch)
        order.extend(epoch[i:i+BATCH] for i in range(0, n, BATCH))
    return order[:STEPS[-1]]


def fit(out, policy, records, states, order, scale):
    head = deepcopy(policy.return_head).requires_grad_(True)
    with torch.no_grad():
        head[-1].weight.div_(scale)
        head[-1].bias.div_(scale)
    optimizer = torch.optim.Adam(head.parameters(), lr=LR)
    checkpoints, losses = {}, []

    def checkpoint(step):
        state = deepcopy(head.state_dict())
        torch.save(state, out / f"head-{scale}-{step:03d}.pt")
        checkpoints[step] = state

    checkpoint(0)
    for step, indices in enumerate(order, 1):
        data = [records[i] for i in indices]
        x, root, returns, lengths, _ = tensors(data, states)
        y = head(x).flatten()
        decoded_loss = ((scale*y - returns[root]).square() / lengths[root]).sum() / len(data)
        loss = ((y - returns[root]/scale).square() / lengths[root]).sum() / len(data)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        assert torch.isfinite(loss)
        losses.append(dict(step=step, mse=loss.item(), decoded_mse=decoded_loss.item()))
        if step in STEPS:
            checkpoint(step)
    return checkpoints, losses


def spread(x):
    return dict(mean=x.mean().item(), sd=x.std(unbiased=False).item(), min=x.min().item(), max=x.max().item())


def score(y, data, records):
    _, root, returns, lengths, starts = data
    error = y - returns[root]
    first = y[starts]
    win = torch.tensor([r["outcome"] == "predicted_win" for r in records])
    comparison = first[win, None] - first[~win][None, :]
    result = dict(mae=(error.abs()/lengths[root]).sum().item()/len(records),
                  rmse=math.sqrt((error.square()/lengths[root]).sum().item()/len(records)),
                  bias=(error/lengths[root]).sum().item()/len(records),
                  auc=((comparison > 0).float() + .5*(comparison == 0)).mean().item(),
                  first_value=spread(first))
    for name, mask in (("win", win), ("death", ~win)):
        result[name] = dict(n=mask.sum().item(), first=spread(first[mask]), actual=spread(returns[mask]))
    return result


@torch.no_grad()
def assess(policy, partitions, states, checkpoints, scale):
    head = deepcopy(policy.return_head)
    initial = checkpoints[0]
    scores = {}
    for step, checkpoint in checkpoints.items():
        head.load_state_dict(checkpoint)
        metrics = {}
        for name, rows in partitions.items():
            data = tensors(rows, states[name])
            metrics[name] = score(scale*head(data[0]).flatten(), data, rows)
        metrics["parameter_delta_l2"] = {k: (v-initial[k]).norm().item() for k, v in checkpoint.items()}
        metrics["decoded_final_delta_l2"] = {k: scale*v for k,v in metrics["parameter_delta_l2"].items()
                                              if k.startswith("2.")}
        metrics["decoded_output_bound"] = scale*(head[-1].weight.abs().sum()+head[-1].bias.abs()).item()
        scores[step] = metrics
    return scores


def main(source, out):
    out.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = read(source / "protocol.json")["config"]
    model, stamp = load_step(source / "training/training.sqlite", 84)
    policy = v4.Policy().eval().requires_grad_(False)
    policy.load_state_dict(model["model"])
    assert model["model_sha256"] == digest(v4.checkpoint_policy(policy)) == MODEL_HASH
    fitting, holdout = split(bank(source, v4.Objective(**cfg["objective"])))
    partitions = {"fit": fitting, "holdout": holdout}
    order = optimizer_order(len(fitting))
    manifests = {name: [{key: val for key,val in row.items() if key != "route"} for row in rows]
                 for name, rows in partitions.items()}
    save(out / "protocol.json", dict(split_seed=SPLIT_SEED, order_seed=ORDER_SEED, lr=LR, batch=BATCH,
                                     fit_order_sha256=digest(order), checkpoints=STEPS,
                                     scale=SCALE, model_sha256=MODEL_HASH, snapshot_sha256=stamp,
                                     split_sha256=digest(manifests), partitions=manifests))
    states = {"fit": cache(policy, fitting)}
    print("Fitting cache ready", flush=True)
    direct_check = direct(policy, fitting[::max(1, len(fitting)//16)], states["fit"])
    raw, raw_loss = fit(out, policy, fitting, states["fit"], order, 1)
    scaled, scaled_loss = fit(out, policy, fitting, states["fit"], order, SCALE)
    # Holdout forward passes are delayed until both fits finish.
    states["holdout"] = cache(policy, holdout)
    x = tensors(holdout, states["holdout"])[0]
    with torch.no_grad():
        head = deepcopy(policy.return_head)
        head.load_state_dict(scaled[0])
        init_error = (policy.return_head(x) - SCALE*head(x)).abs().max().item()
        assert init_error < 2e-5
    print("Both fits complete; scoring fixed checkpoints", flush=True)
    held = tensors(holdout, states["holdout"])
    mean = sum(r["reward"] for r in fitting)/len(fitting)
    med = median(r["reward"] for r in fitting)
    constant = {key: score(torch.full_like(held[0][:,0], value), held, holdout)
                for key, value in (("fit_mean", mean), ("fit_median", med))}
    assert digest(v4.checkpoint_policy(policy)) == MODEL_HASH
    balance = {name: {key: Counter(str(row[key]) for row in rows)
                      for key in ("character", "act", "stage", "outcome")}
               for name, rows in partitions.items()}
    save(out / "results.json", dict(init_decode_error=init_error, cache_check=direct_check, balance=balance,
                                    raw=assess(policy, partitions, states, raw, 1),
                                    normalized=assess(policy, partitions, states, scaled, SCALE),
                                    constants=constant, training_loss={"raw": raw_loss, "normalized": scaled_loss}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a2", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.a2, args.output)
