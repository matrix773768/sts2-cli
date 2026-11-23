"""One on-policy policy-gradient update from checksum-bound public NOSL rollouts."""
import argparse
import gzip
import json
import math
from pathlib import Path

import torch
from torch.nn import functional as F

from features import Encoder
from prepare import collate, checksum
from train import atomic_save, load_policy
from network import VERSION


def tune_encoder(model, stage):
    model.encoder.requires_grad_(stage == "all")
    if stage == "interaction":
        model.encoder.interactions.requires_grad_(True)
        model.encoder.condition.requires_grad_(True)


def experiences(rollouts, encoder, expected_sha):
    for line in rollouts:
        record = json.loads(line)
        if (record["behavior"]["model"] != VERSION
                or record["behavior"]["model_sha256"] != expected_sha
                or record["behavior"]["mode"] != "sample"
                or record["evidence"] != "prediction_only"):
            raise ValueError("On-policy update requires the exact rollout checkpoint")
        if not record["complete"]:
            continue
        terminal = record["terminal"]
        outcome = 1.+.25*terminal["hp"]/terminal["max_hp"] if record["status"] == "predicted_win" else -1.
        history = encoder.initial_history()
        for step in record["steps"]:
            obs, action = step["observation"], step["action"]
            if not step["advanced"] or obs["actions"][action["index"]] != action:
                raise ValueError("Invalid recorded action")
            feature = encoder.encode(obs, history)
            yield feature | dict(chosen=action["index"], recorded=step["behavior_logp"],
                                 reward=outcome, weight=1./record["length"])
            history = encoder.update(history, obs, action)


def update(checkpoint, rollout, output, stage, device, lr, batch_size):
    output.mkdir()
    model, vocab = load_policy(checkpoint, device)
    tune_encoder(model, stage)
    model.train()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),lr=lr)
    encoder = Encoder(vocab)
    expected = checksum(checkpoint)
    rows = []
    updates = 0
    objective = 0.

    def parts():
        with gzip.open(rollout,"rt",encoding="utf-8") as stream:
            yield from experiences(stream,encoder,expected)

    # Compute a trajectory-weighted control variate and check the frozen
    # behavior numerically before taking any gradient.
    sum_reward, count = 0., 0.
    for feature in parts():
        sum_reward += feature["reward"]*feature["weight"]
        count += feature["weight"]
    if count <= 0:
        raise ValueError("No complete on-policy trajectories")
    baseline = sum_reward/count
    largest_difference = 0.

    def gradient(batch):
        nonlocal updates, objective, largest_difference
        tensors = {k:torch.from_numpy(v).to(device) for k,v in collate(batch).items()}
        logits = model(tensors)
        logp = -F.cross_entropy(logits,tensors["chosen"].long(),reduction="none")
        difference = (logp.detach()-tensors["recorded"]).abs().max().item()
        largest_difference = max(largest_difference, difference)
        if difference > 3e-5:
            raise ValueError(f"Rollout behavior logp mismatch {difference}")
        loss = -(logp*(tensors["reward"]-baseline)*tensors["weight"]).sum()/count
        loss.backward()
        objective += loss.item()
        updates += 1

    for feature in parts():
        rows.append(feature)
        if len(rows) == batch_size:
            gradient(rows)
            rows.clear()
    if rows:
        gradient(rows)
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
    if not math.isfinite(objective):
        raise FloatingPointError("Invalid policy-gradient loss")
    optimizer.step()
    payload = torch.load(checkpoint,map_location="cpu",weights_only=True)
    payload["model"] = model.state_dict()
    atomic_save(output/"policy.pt",payload)
    atomic_save(output/"resume.pt",dict(optimizer=optimizer.state_dict(),model=model.state_dict(),
                encoder_stage=stage,source=expected,rng=torch.get_rng_state(),
                rollout_sha256=checksum(rollout),learning_rate=lr))
    report = dict(complete=round(count),minibatches=updates,optimizer_steps=1,loss=objective,
                  baseline=baseline,max_behavior_logp_difference=largest_difference,gradient_norm=norm.item(),
                  stage=stage,output_sha256=checksum(output/"policy.pt"))
    (output/"update.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint",type=Path)
    p.add_argument("rollout",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--stage",choices=("frozen","interaction","all"),default="frozen")
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    p.add_argument("--batch",type=int,default=256)
    p.add_argument("--lr",type=float,default=1e-4)
    a=p.parse_args()
    print(json.dumps(update(a.checkpoint,a.rollout,a.output,a.stage,a.device,a.lr,a.batch),indent=2))
