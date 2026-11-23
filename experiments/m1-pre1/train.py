"""Train all PRE1 objectives with replayable feature-shard checkpoints."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import random
from time import perf_counter, process_time

import numpy as np
import torch
from torch.nn import functional as F

from features import HERE
from network import Network, VERSION
from prepare import checksum


def masked(loss, mask):
    return torch.where(mask, loss, 0.).sum() / mask.sum().clamp_min(1)


def objectives(net, batch, weights, mode, logit_penalty=0.):
    logits, delta, outcome, signed = net(batch, aux=True)
    mask = batch["delta_mask"]
    relation = batch["order_mask"]
    teacher = batch["source"] == 1
    step = (delta - batch["delta"]).square().mean(1)
    wanted = batch["outcome"]
    terminal = (F.binary_cross_entropy_with_logits(outcome[:, 0], wanted[:, 0], reduction="none")
                + F.binary_cross_entropy_with_logits(outcome[:, 3], wanted[:, 3], reduction="none")
                + F.smooth_l1_loss(outcome[:, [1,2,4,5]], wanted[:, [1,2,4,5]], reduction="none").sum(1))
    order = F.binary_cross_entropy_with_logits(signed, batch["order"], reduction="none")
    nll = F.cross_entropy(logits, batch["chosen"].long(), reduction="none")
    losses = (masked(step, mask), masked(order, relation), terminal.mean(), masked(nll, teacher))
    total = (weights[3]*losses[3] if mode == "behavior" else
             sum(weights[i]*losses[i] for i in range(3 if mode == "mechanism" else 4)))
    if mode == "behavior" and logit_penalty:
        # Legal-menu log likelihood does not constrain the common logit
        # offset. Constrain both offset and score scale during BC adaptation.
        legal = torch.where(batch["mask"], logits.float(), 0.)
        rms_square = legal.square().sum(1)/batch["mask"].sum(1).clamp_min(1)
        total = total + logit_penalty*masked(rms_square, teacher)
    measures = torch.stack((torch.where(mask, step, 0.).sum(), mask.sum(),
                            torch.where(relation, order, 0.).sum(), relation.sum(),
                            terminal.sum(), teacher.new_tensor(len(teacher), dtype=torch.long),
                            torch.where(teacher, nll, 0.).sum(), teacher.sum(),
                            (((signed >= 0) == (batch["order"] == 1)) & relation).sum(),
                            ((logits.argmax(1) == batch["chosen"]) & teacher).sum(),
                            torch.where(teacher, (outcome[:, 0].sigmoid()-wanted[:, 0]).square(),0.).sum(),
                            torch.where(~teacher, (outcome[:, 0].sigmoid()-wanted[:, 0]).square(),0.).sum()))
    return total, measures.detach()


def summarize(x):
    step, step_n, relation, relation_n, value, n, imitation, teacher_n, order_hits, teacher_hits, a2, p0 = x
    ratio = lambda num, den: num / den if den else None
    return dict(rows=int(n), dynamics_n=int(step_n), order_n=int(relation_n), teacher_n=int(teacher_n),
                dynamics=ratio(step, step_n), order=ratio(relation, relation_n), value=ratio(value, n),
                teacher_nll=ratio(imitation, teacher_n), order_accuracy=ratio(order_hits, relation_n),
                teacher_top1=ratio(teacher_hits, teacher_n), a2_win_brier=ratio(a2, teacher_n),
                p0_win_brier=ratio(p0,n-teacher_n))


def load_shard(root, descriptor):
    with np.load(root / descriptor["name"], allow_pickle=False) as file:
        return {name: file[name] for name in file.files}


def minibatches(arrays, size, device, rng):
    length = len(arrays["source"])
    order = rng.permutation(length) if rng is not None else np.arange(length)
    for start in range(0, length, size):
        inds = order[start:start+size]
        yield {name: torch.from_numpy(array[inds]).to(device) for name, array in arrays.items()}


@torch.inference_mode()
def evaluate(net, root, shards, size, device, weights):
    net.eval()
    stats = torch.zeros(12, device=device)
    for shard in shards:
        for batch in minibatches(load_shard(root, shard), size, device, None):
            _, part = objectives(net, batch, weights, "joint")
            stats += part
    return summarize(stats.tolist())


def atomic_save(path, value):
    temp = path.with_suffix(".partial")
    torch.save(value, temp)
    temp.replace(path)


def export(path, net, vocabulary, identity):
    atomic_save(path, dict(version=VERSION, vocabulary=vocabulary, width=net.encoder.width,
                           n2e_sha256=identity["n2e_sha256"], feature_sha256=checksum(HERE/"features.py"), network_sha256=checksum(HERE/"network.py"),
                           model=net.state_dict()))


def load_policy(path, device="cpu"):
    from features import CATALOG_PATH
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if (saved["version"] != VERSION or saved["n2e_sha256"] != checksum(CATALOG_PATH)
            or saved["feature_sha256"] != checksum(HERE/"features.py")
            or saved["network_sha256"] != checksum(HERE/"network.py")):
        raise ValueError("Weight feature contract or N2E digest differs")
    net = Network(saved["vocabulary"], saved["width"])
    net.load_state_dict(saved["model"])
    return net.to(device).eval(), saved["vocabulary"]


def train(root, output, config, device, until=None, smoke=False, mode="standard", start_weights=None):
    wall_start, cpu_start = perf_counter(), process_time()
    output.mkdir(exist_ok=True)
    if (mode == "transfer") != (start_weights is not None):
        raise ValueError("Transfer requires exactly one source encoder checkpoint")
    manifest = json.loads((root/"manifest.json").read_bytes())
    available = sum(n for key,n in manifest["stats"].items() if key.endswith("_trajectories"))
    if not smoke and (available < 50000 or not manifest["stats"].get("train_0_trajectories")
                      or not manifest["stats"].get("train_1_trajectories")):
        raise ValueError("Formal training requires both training sources and a 50,000-trajectory corpus")
    for group in manifest["shards"].values():
        for shard in group:
            if checksum(root/shard["name"]) != shard["sha256"]:
                raise ValueError(f"Feature shard damaged: {shard['name']}")
    identity = dict(features=checksum(root/"manifest.json"), config=config, device=device, torch=str(torch.__version__), mode=mode,
                    initializer=checksum(start_weights) if start_weights else None,
                    sources={name: checksum(HERE/name) for name in ("network.py","train.py","features.py")}, smoke=smoke)
    randomness = config["seed"]
    torch.manual_seed(randomness)
    random.seed(randomness)
    threads = 2 if smoke or device == "cuda" else min(6, os.cpu_count() or 1)
    torch.set_num_threads(threads)
    identity["threads"] = threads
    if device == "cuda":
        torch.set_float32_matmul_precision("high")
    use_bfloat = device == "cuda" and torch.cuda.is_bf16_supported()
    identity["precision"] = "bfloat16_autocast" if use_bfloat else "float32"
    vocabulary = manifest["identity"]["vocabulary"]
    net = Network(vocabulary, config["width"]).to(device)
    if start_weights is not None:
        saved_policy, saved_vocabulary = load_policy(start_weights)
        if saved_vocabulary != vocabulary or saved_policy.encoder.width != config["width"]:
            raise ValueError("Transfer feature identity differs")
        net.encoder.load_state_dict(saved_policy.encoder.state_dict())
    # The transfer arms start from the same seeded Actor and optimizer, with
    # matching data order and exactly the same 10 epochs of adaptation.
    epochs = config["epochs"] if mode == "standard" else config["epochs"]-config["mechanism_epochs"]
    if epochs < 1:
        raise ValueError("Empty optimization schedule")
    optimizer = torch.optim.AdamW(net.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"],
                                  fused=device == "cuda")
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, epochs, eta_min=config["learning_rate"]*.1)
    checkpoint = output/"resume.pt"
    train_shards = manifest["shards"]["train"]
    val_shards = manifest["shards"]["validation"]
    batch_size = config["batch"]
    weights = config["weights"]
    curve, epoch, cursor, updates, elapsed = [], 0, 0, 0, 0.
    stats = torch.zeros(12, device=device)
    prior_cpu = 0.
    if checkpoint.exists():
        saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if saved["identity"] != identity:
            raise ValueError("Checkpoint identity mismatch")
        net.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        scheduler.load_state_dict(saved["scheduler"])
        torch.set_rng_state(saved["rng_cpu"])
        if device == "cuda":
            torch.cuda.set_rng_state_all(saved["rng_cuda"])
        random.setstate(saved["rng_python"])
        curve, epoch, cursor, updates, elapsed = (saved[k] for k in ("curve","epoch","cursor","updates","elapsed"))
        stats = saved["stats"].to(device)
        prior_cpu = saved["cpu_seconds"]
    else:
        export(output/"initial.pt", net, vocabulary, manifest["identity"])
        initial = evaluate(net, root, val_shards, batch_size, device, weights)
        curve.append(dict(epoch=0, validation=initial, updates=0))
    tick = perf_counter()

    def save():
        atomic_save(checkpoint, dict(identity=identity, model=net.state_dict(), optimizer=optimizer.state_dict(),
                    scheduler=scheduler.state_dict(), rng_cpu=torch.get_rng_state(), rng_python=random.getstate(),
                    rng_cuda=torch.cuda.get_rng_state_all() if device == "cuda" else [],
                    curve=curve, epoch=epoch, cursor=cursor, updates=updates,
                    elapsed=elapsed+perf_counter()-tick, stats=stats,
                    cpu_seconds=prior_cpu+process_time()-cpu_start))
        partial = output/"curve.partial"
        partial.write_text(json.dumps(curve, indent=2, allow_nan=False), encoding="utf-8")
        partial.replace(output/"curve.json")

    while epoch < min(epochs, until if until is not None else epochs):
        net.train()
        phase = ("behavior" if mode != "standard" else
                 "mechanism" if epoch < config["mechanism_epochs"] else "joint")
        order = np.random.default_rng([randomness, epoch]).permutation(len(train_shards))
        while cursor < len(order):
            index = int(order[cursor])
            arrays = load_shard(root, train_shards[index])
            if phase == "behavior":
                teacher = arrays["source"] == 1
                arrays = {name: array[teacher] for name, array in arrays.items()}
            for batch in minibatches(arrays, batch_size, device,
                                     np.random.default_rng([randomness, epoch, index])):
                optimizer.zero_grad(set_to_none=True)
                precision = torch.autocast("cuda", dtype=torch.bfloat16) if use_bfloat else nullcontext()
                with precision:
                    loss, measures = objectives(net, batch, weights, phase, config.get("logit_penalty",0.))
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), config["clip"], error_if_nonfinite=True)
                optimizer.step()
                stats += measures
                updates += 1
            cursor += 1
            if cursor % 16 == 0 or (output/"STOP").exists():
                save()
                if (output/"STOP").exists():
                    return
        current_train = summarize(stats.tolist())
        before_lr = scheduler.get_last_lr()[0]
        scheduler.step()
        epoch += 1
        cursor = 0
        stats.zero_()
        val = evaluate(net, root, val_shards, batch_size, device, weights)
        record = dict(epoch=epoch, optimization=phase,
                      train=current_train, validation=val, updates=updates, learning_rate=before_lr,
                      elapsed=elapsed+perf_counter()-tick)
        curve.append(record)
        if mode == "standard" and epoch == config["mechanism_epochs"]:
            export(output/"mechanism.pt", net, vocabulary, manifest["identity"])
        if epoch == epochs:
            export(output/"final.pt", net, vocabulary, manifest["identity"])
            atomic_save(output/"encoder.pt", dict(version=VERSION, width=net.encoder.width,
                      vocabulary=vocabulary, n2e_sha256=manifest["identity"]["n2e_sha256"],
                      feature_sha256=checksum(HERE/"features.py"), network_sha256=checksum(HERE/"network.py"), encoder=net.encoder.state_dict()))
        save()
        print(json.dumps(record, allow_nan=False), flush=True)
    if epoch == epochs:
        summary = dict(evaluation=evaluate(net, root, manifest["shards"]["evaluation"], batch_size, device, weights),
                       parameters=sum(p.numel() for p in net.parameters()), elapsed=elapsed+perf_counter()-tick,
                       precision=identity["precision"], epochs=epochs,
                       decision_examples=epochs*(sum(shard["rows"] for shard in train_shards)
                                                  if mode == "standard" else manifest["stats"]["train_1_rows"]),
                       updates=updates, device=device,threads=threads,
                       cpu_seconds=prior_cpu+process_time()-cpu_start,
                       wall_seconds_this_invocation=perf_counter()-wall_start,
                       peak_cuda_bytes=torch.cuda.max_memory_allocated() if device=="cuda" else None)
        (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE/"schedule.json")
    parser.add_argument("--device", choices=("cpu","cuda"), default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--until", type=int)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--mode", choices=("standard","behavior","transfer"), default="standard")
    parser.add_argument("--start-weights", type=Path)
    args = parser.parse_args()
    train(args.features, args.output, json.loads(args.config.read_bytes()), args.device, args.until, args.smoke, args.mode, args.start_weights)
