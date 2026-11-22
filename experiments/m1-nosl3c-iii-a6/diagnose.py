"""Frozen outcome probes and same-function gradient controls."""
from collections import Counter
from copy import deepcopy
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / relative)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


a4 = module("a4_fit", "m1-nosl3c-iii-a4/fit.py")
a3 = module("a3_gradients", "m1-nosl3c-iii-a3/analyze.py")
torch, v4, read, save, digest = a4.torch, a4.v4, a4.read, a4.save, a4.digest
nn = torch.nn
SEED = 73192601
MID = 8
STEPS = (1, 12, 36)
SCALE = 100
PROBE_STEPS = 200
LR = .01
L2 = .01


def partition(records):
    rng = random.Random(SEED)
    splits = {"fit": [], "validation": [], "time_test": []}
    for status in ("predicted_win", "death"):
        early = [r for r in records if int(r["key"].split(":")[0]) < 36 and r["outcome"] == status]
        rng.shuffle(early)
        n = round(len(early)/5)
        splits["validation"].extend(early[:n])
        splits["fit"].extend(early[n:])
    splits["time_test"] = [r for r in records if int(r["key"].split(":")[0]) >= 36]
    assert len({r["root"] for group in splits.values() for r in group}) == sum(map(len,splits.values())) == 1419
    return splits


def score(probability, labels, cut):
    win, loss = probability[labels], probability[~labels]
    auc = None
    balanced = None
    if len(win) and len(loss):
        d = win[:, None] - loss[None, :]
        auc = ((d > 0).float() + .5*(d == 0)).mean().item()
        balanced = ((win >= cut).float().mean() + (loss < cut).float().mean()).item()/2
    return dict(n=len(labels), deaths=len(loss), auc=auc, balanced_accuracy=balanced,
                brier=(probability-labels.float()).square().mean().item(),
                predicted_mean=probability.mean().item(), predicted_sd=probability.std(unbiased=False).item(),
                win_mean=win.mean().item() if len(win) else None, death_mean=loss.mean().item() if len(loss) else None)


def probes(rows, cache, index):
    x, y = {}, {}
    for name, group in rows.items():
        x[name] = torch.stack([cache[r["key"]][index] for r in group])
        y[name] = torch.tensor([r["outcome"] == "predicted_win" for r in group])
    center = x["fit"].mean(0)
    scale = x["fit"].std(0, unbiased=False).clamp_min(1e-6)
    x = {key: (values-center)/scale for key, values in x.items()}
    prevalence = y["fit"].float().mean().item()
    fits, descriptions = {}, {}
    for name in ("constant", "logistic", "mlp"):
        if name == "constant":
            predictions = {key: torch.full_like(labels, prevalence, dtype=torch.float32)
                           for key, labels in y.items()}
        else:
            torch.manual_seed(SEED)
            width = x["fit"].shape[1]
            model = nn.Linear(width, 1) if name == "logistic" else nn.Sequential(
                nn.Linear(width, 8), nn.Tanh(), nn.Linear(8, 1))
            optimizer = torch.optim.Adam(model.parameters(), lr=LR)
            for _ in range(PROBE_STEPS):
                logits = model(x["fit"]).flatten()
                penalty = sum(p.square().sum() for p in model.parameters() if p.ndim > 1)
                loss = nn.functional.binary_cross_entropy_with_logits(logits, y["fit"].float()) + L2*penalty/2
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            with torch.no_grad():
                predictions = {key: model(features).flatten().sigmoid() for key, features in x.items()}
            descriptions[name] = {k: p.detach().tolist() for k,p in model.state_dict().items()}
        fits[name] = {key: score(values, y[key], prevalence) for key, values in predictions.items()}
        test = rows["time_test"]
        fits[name]["test_groups"] = {}
        for field in ("character", "act", "stage"):
            for group in sorted({r[field] for r in test}):
                mask = torch.tensor([r[field] == group for r in test])
                fits[name]["test_groups"][f"{field}:{group}"] = score(
                    predictions["time_test"][mask], y["time_test"][mask], prevalence)
        fits[name]["test_predictions"] = {r["key"]: float(pred) for r,pred in
                                            zip(test, predictions["time_test"], strict=True)}
    return dict(prevalence=prevalence, measured=fits, weights=descriptions)


def cosine(a, b):
    length = a.norm().item() * b.norm().item()
    return torch.dot(a,b).item()/length if length else None


def gradient_diagnosis(source, a5, cfg, step):
    before, _, stamp, _, rows = a3.fixtures(source, step)
    original = v4.Policy().eval()
    original.load_state_dict(before["model"])
    assert digest(v4.checkpoint_policy(original)) == before["model_sha256"]
    reparam = deepcopy(original)
    with torch.no_grad():
        reparam.return_head[-1].weight.div_(SCALE)
        reparam.return_head[-1].bias.div_(SCALE)
    if step == 1:
        candidate, _ = a4.load_step(a5 / "training/training.sqlite", 0)
        assert all(torch.equal(value, candidate["model"][key]) for key,value in reparam.state_dict().items())
        assert not read(a5 / "first-batch-gate.json")["differences"]
    normal_cfg = cfg | {"a5":{"value_scale":SCALE}}
    old, raw_loss, _ = a3.decompose(original, rows, cfg)
    small, _, _ = a3.decompose(reparam, rows, normal_cfg)
    matched, match_loss, _ = a3.decompose(reparam, rows, normal_cfg, decoded_critic_loss=True)
    hist = read(source / "training" / f"metrics-{step:02d}.json")["stats"]
    assert raw_loss["critic_loss"] == hist["critic_loss"]

    public = [dict(key=str(i), route=row["transitions"]) for i,row in enumerate(rows)]
    states = torch.cat(list(a4.cache(original, public).values()))
    with torch.no_grad():
        old_v = original.return_head(states).flatten()
        new_v = SCALE * reparam.return_head(states).flatten()
        objective = v4.Objective(**cfg["objective"])
        ordered = sorted(public, key=lambda r: -len(r["route"]))
        rewards = torch.cat([torch.full((len(item["route"]),), objective.reward(
            rows[int(item["key"])]["feedback"], rows[int(item["key"])]["hp_accounting"]["initial_hp"]))
                             for item in ordered])
        max_value = (old_v-new_v).abs().max().item()
        max_advantage = ((rewards-old_v)-(rewards-new_v)).abs().max().item()
        assert max_value < 2e-6 and max_advantage < 2e-5
    names = [key for key,_ in original.named_parameters()]
    indices = {
        "all": list(range(len(names))),
        "shared": [i for i,k in enumerate(names) if not k.startswith(("actor.", "return_head.", "relation."))],
        "state": [i for i,k in enumerate(names) if k.startswith("state.")],
        "critic_head": [i for i,k in enumerate(names) if k.startswith("return_head.")],
        "critic_hidden": [i for i,k in enumerate(names) if k.startswith("return_head.0.")],
        "critic_readout": [i for i,k in enumerate(names) if k.startswith("return_head.2.")],
    }
    result = {}
    for arm, gradients in (("original",old),("normalized",small),("matched",matched)):
        groups = {}
        for name, group in indices.items():
            actor, critic, entropy = [a3.flat(gradients[term],group) for term in a3.TERMS]
            origin = a3.flat(old["critic_weighted"], group)
            groups[name] = dict(critic=critic.norm().item(), actor=actor.norm().item(),
                                entropy=entropy.norm().item(), total=(actor+critic+entropy).norm().item(),
                                cosine_to_original=cosine(critic,origin), cosine_to_actor=cosine(critic,actor),
                                ratio_to_original=critic.norm().item()/origin.norm().item())
        result[arm] = groups | {"clip_factor":min(1,cfg["grad_clip"]/(groups["all"]["total"]+1e-6))}
    assert abs(result["original"]["all"]["total"] - hist["grad_norm"]) / hist["grad_norm"] < 1e-5
    for group in ("shared","state","critic_hidden"):
        assert abs(result["normalized"][group]["ratio_to_original"]*SCALE**2-1) < 1e-4
        assert abs(result["matched"][group]["ratio_to_original"]-1) < 1e-4
        assert result["matched"][group]["cosine_to_original"] > .99999
    assert abs(result["matched"]["critic_readout"]["ratio_to_original"]/SCALE-1) < 1e-4
    return dict(update=step, pre_snapshot=stamp, model_sha256=before["model_sha256"], n=len(rows),
                history_norm=hist["grad_norm"], matched_critic_loss_difference=match_loss["critic_loss"]-raw_loss["critic_loss"],
                max_value=max_value,max_advantage=max_advantage, arms=result)


def main(source, a5, out):
    out.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cfg = read(source / "protocol.json")["config"]
    model, stamp = a4.load_step(source / "training/training.sqlite",36)
    policy = v4.Policy().eval().requires_grad_(False)
    policy.load_state_dict(model["model"])
    assert digest(v4.checkpoint_policy(policy)) == model["model_sha256"]
    records = a4.bank(source,v4.Objective(**cfg["objective"]))
    splits = partition(records)
    manifest = {key: [{k:v for k,v in r.items() if k not in ("route","reward")} for r in group]
                for key,group in splits.items()}
    save(out / "protocol.json",dict(seed=SEED, mid_zero_based=MID, steps=PROBE_STEPS, lr=LR,
                                    l2=L2, mlp_hidden=8, model_sha256=model["model_sha256"],
                                    snapshot_sha256=stamp, splits=manifest, split_hash=digest(manifest),
                                    gradient_steps=STEPS, scale=SCALE))
    # Replay at most the fixed nine decisions. No suffix enters the probe input.
    prefixes = [r | {"route":r["route"][:MID+1]} for r in records]
    cache = a4.cache(policy,prefixes)
    results = {}
    for name,index in (("first",0),("mid",MID)):
        rows = {key:[r for r in group if len(cache[r["key"]])>index] for key,group in splits.items()}
        results[name] = probes(rows,cache,index)
        if index:
            results["first_on_mid_roots"] = probes(rows,cache,0)
    save(out / "probes.json",results)
    print("Frozen probes complete",flush=True)
    gradients = []
    for step in STEPS:
        gradients.append(gradient_diagnosis(source,a5,cfg,step))
        save(out / "gradients.json",gradients)
        print(f"Verified gradient control {step}",flush=True)


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
