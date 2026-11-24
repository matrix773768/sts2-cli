"""Matched resumable Monte Carlo training of V and Q."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import random
from time import perf_counter

import numpy as np
import torch
from torch.nn import functional as F

from sv_data import ROOT, checksum, config, write_json
from sv_model import VERSION, ValueNet, contract, model_spec
from train import atomic_save, load_policy, load_shard


def sample_rows(arrays, count, rng):
    trajectory = arrays["trajectory"]
    _, starts, sizes = np.unique(trajectory, return_index=True, return_counts=True)
    maximum = np.minimum(sizes, count)
    order = np.lexsort((rng.random(len(trajectory)), trajectory))
    selected = order[np.arange(len(order)) - np.repeat(starts, sizes) < np.repeat(maximum, sizes)]
    weights = np.repeat(1 / maximum, sizes).astype(np.float32)
    rng.shuffle(selected)
    return selected, weights


def batches(arrays, batch_size, device, count=None, rng=None):
    if count is None:
        rows, weights = np.arange(len(arrays["cls"])), arrays["weight"]
    else:
        rows, weights = sample_rows(arrays, count, rng)
    for offset in range(0, len(rows), batch_size):
        selection = rows[offset:offset + batch_size]
        batch = {key: torch.from_numpy(value[selection]).to(device) for key, value in arrays.items()
                 if key not in ("trajectory", "old_logp", "weight")}
        batch["weight"] = torch.from_numpy(weights[selection]).to(device)
        yield batch


def losses(net, outcome, batch):
    logits, max_delta = net.split(outcome)
    target = batch["cls"].long()
    nll = F.cross_entropy(logits, target, reduction="none")
    growth = max_delta.gather(1, (target - 1).clamp_min(0)[:, None])[:, 0]
    growth_aux = F.smooth_l1_loss(growth, batch["max_delta"], reduction="none") * target.ne(0)
    return nll, growth_aux


def amp(device, bf16):
    return torch.autocast(device, dtype=torch.bfloat16) if bf16 else nullcontext()


@torch.inference_mode()
def validate(model, shards, batch, device, bf16):
    model.eval()
    total = torch.zeros(5, device=device)
    for arrays in shards:
        for data in batches(arrays, batch, device, 4, np.random.default_rng(71393204)):
            with amp(device, bf16):
                predictions = model(data, chosen_only=True)
            terms = [(losses(model, output, data)[0], model.probabilities(output)[:, 0])
                     for output in predictions]
            labels = data["cls"].eq(0)
            wt = data["weight"]
            total += torch.stack([wt.sum(), *((wt * nll).sum() for nll, _ in terms),
                                  *((wt * (p - labels.float()).square()).sum() for _, p in terms)])
    n, *metrics = total.tolist()
    return dict(zip(("v_nll", "q_nll", "v_brier", "q_brier"), (value / n for value in metrics)))


def train_arm(root, manifest, shards, out, cfg, arm, seed, device, until=None, warm=None):
    out.mkdir(parents=True, exist_ok=True)
    bf16 = device == "cuda" and torch.cuda.is_bf16_supported()
    torch.manual_seed(seed)
    random.seed(seed)
    model = ValueNet(manifest["vocabulary"], **model_spec(cfg)).to(device)
    initializer = ROOT / cfg["pre1"] if arm == "pre1" else None
    if initializer:
        parent, vocabulary = load_policy(initializer)
        if vocabulary != manifest["vocabulary"] or parent.encoder.width != cfg["width"]:
            raise ValueError("PRE1 transfer shape changed")
        model.encoder.load_state_dict(parent.encoder.state_dict())
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"],
                                  fused=device == "cuda")
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, cfg["epochs"], eta_min=cfg["lr"] * .1)
    identity = dict(data=checksum(root / "manifest.json"), cfg=cfg, arm=arm, seed=seed, sources=contract(),
                    training=checksum(Path(__file__)), torch=str(torch.__version__), device=device, bf16=bf16,
                    initializer=checksum(initializer) if initializer else None,
                    continuation=checksum(warm) if warm else None)
    saved = out / "resume.pt"
    best, epoch, updates, presents, seconds, curve = float("inf"), 0, 0, 0, 0., []
    if saved.exists():
        snapshot = torch.load(saved, map_location="cpu", weights_only=True)
        if snapshot["identity"] != identity:
            raise ValueError("Resume identity changed")
        model.load_state_dict(snapshot["model"])
        optimizer.load_state_dict(snapshot["optimizer"])
        schedule.load_state_dict(snapshot["scheduler"])
        torch.set_rng_state(snapshot["cpu_rng"])
        if device == "cuda":
            torch.cuda.set_rng_state_all(snapshot["cuda_rng"])
        random.setstate(snapshot["python_rng"])
        best, epoch, updates, presents, seconds, curve = (snapshot[name] for name in
            ("best", "epoch", "updates", "presents", "seconds", "curve"))
    elif warm:
        snapshot = torch.load(warm, map_location="cpu", weights_only=True)
        model.load_state_dict(snapshot["model"])
        optimizer.load_state_dict(snapshot["optimizer"])
        for group in optimizer.param_groups:
            group["lr"] = cfg["lr"]
    if not curve:
        curve.append(dict(epoch=0, validation=validate(model, shards["validation"], cfg["batch"], device, bf16)))
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    end = min(cfg["epochs"], until if until is not None else cfg["epochs"])
    for number in range(epoch + 1, end + 1):
        if (out / "STOP").exists():
            break
        begin = perf_counter()
        model.train()
        rng = np.random.default_rng([seed, number])
        metrics = torch.zeros(3, device=device)
        for index in rng.permutation(len(shards["train"])):
            for batch in batches(shards["train"][index], cfg["batch"], device, cfg["epoch_draws"], rng):
                optimizer.zero_grad(set_to_none=True)
                with amp(device, bf16):
                    predictions = model(batch, chosen_only=True)
                wt = batch["weight"]
                terms = [losses(model, outcome, batch) for outcome in predictions]
                objective = sum((wt * (nll + .04 * growth)).sum() for nll, growth in terms) / wt.sum()
                objective.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step()
                metrics += torch.stack([wt.sum(), *((wt * nll.detach()).sum() for nll, _ in terms)])
                updates += 1
                presents += len(wt)
        measure = validate(model, shards["validation"], cfg["batch"], device, bf16)
        if not all(np.isfinite(v) for v in measure.values()):
            raise FloatingPointError("Non-finite validation metric")
        score = measure["v_nll"] + measure["q_nll"]
        schedule.step()
        effective, v_loss, q_loss = metrics.tolist()
        seconds += perf_counter() - begin
        curve.append(dict(epoch=number, updates=updates, presents=presents, validation=measure,
                          train_v_nll=v_loss / effective, train_q_nll=q_loss / effective, seconds=seconds))
        if score < best:
            best = score
            atomic_save(out / "best.pt", dict(version=VERSION, model=model.state_dict(), spec=model_spec(cfg),
                vocabulary=manifest["vocabulary"], policies=manifest["policies"], sources=contract(),
                epoch=number, identity=identity))
        atomic_save(saved, dict(identity=identity, model=model.state_dict(), optimizer=optimizer.state_dict(),
            scheduler=schedule.state_dict(), cpu_rng=torch.get_rng_state(), python_rng=random.getstate(),
            cuda_rng=torch.cuda.get_rng_state_all() if device == "cuda" else [], best=best, epoch=number,
            updates=updates, presents=presents, seconds=seconds, curve=curve))
        write_json(out / "summary.json", dict(curve=curve, epochs=number, parameters=sum(p.numel() for p in model.parameters()),
            updates=updates, presents=presents, seconds=seconds, device=device, bf16=bf16,
            peak_allocated=torch.cuda.max_memory_allocated() if device == "cuda" else None,
            best_sha256=checksum(out / "best.pt"), resume_sha256=checksum(saved)))
        print(arm, seed, curve[-1], flush=True)


def load_data(root, limit=None):
    manifest = json.loads((root / "manifest.json").read_bytes())
    shards = {}
    for phase, group in manifest["shards"].items():
        shards[phase] = []
        for descriptor in group[:limit]:
            if checksum(root / descriptor["name"]) != descriptor["sha256"]:
                raise ValueError("Changed value training shard")
            shards[phase].append(load_shard(root, descriptor))
    return manifest, shards


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--arm", choices=("random", "pre1", "both"), default="both")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--until", type=int)
    parser.add_argument("--warm", type=Path)
    parser.add_argument("--smoke-shards", type=int)
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("high")
    cfg = config()
    if args.smoke_shards:
        cfg = cfg | {"smoke_shards": args.smoke_shards}
    manifest, shards = load_data(args.data, args.smoke_shards)
    for arm in ("random", "pre1") if args.arm == "both" else [args.arm]:
        for seed in [args.seed] if args.seed is not None else cfg["seeds"]:
            train_arm(args.data, manifest, shards, args.output / f"{arm}-{seed}", cfg, arm, seed,
                      args.device, args.until, args.warm)
