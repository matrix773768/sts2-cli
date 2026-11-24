"""Replay recorded public prefixes to reconstruct exact frozen behavior probabilities."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import random

import numpy as np
import torch

from sv_data import Encoder, ROOT, checksum, config, db_for, decoded, write_json
from sv_model import load
from sv_runtime import score_public
from evaluate import bind, teacher
from features import SOURCE_HASHES


@torch.inference_mode()
def sample(runtime, behavior, path, encoder, seed, count, policy):
    rng = random.Random(seed)
    target = runtime["targets"]
    examples = []
    max_gap = 0.
    with closing(db_for(path)) as db:
        pool = db.execute("""
            SELECT ordinal FROM trajectories WHERE complete=1 AND split='validation' ORDER BY ordinal
        """).fetchall()
        for ordinal, in rng.sample(pool, count):
            sha, blob = db.execute("SELECT sha,payload FROM trajectories WHERE ordinal=?", (ordinal,)).fetchone()
            row = decoded(sha, blob)
            if row["behavior"]["model_sha256"] != SOURCE_HASHES[policy]:
                raise ValueError("Wrong behavior in consistency subset")
            stop = rng.randrange(len(row["steps"]))
            memory = torch.zeros(target.base.WIDTH)
            public = encoder.initial_history()
            for step in row["steps"][:stop+1]:
                obs, action = step["observation"], step["action"]
                index = action["index"]
                logits, _, state, actions = behavior(target.Decision(obs), memory)
                logp = logits.log_softmax(0)
                max_gap = max(max_gap, abs(logp[index].item() - step["behavior_logp"]))
                if step["position"] == stop:
                    examples.append((row["id"], stop, (obs, public, policy), logp.exp().numpy()))
                else:
                    memory = behavior.remember(memory, state, actions[index])
                    public = encoder.update(public, obs, action)
    if max_gap > 3e-5:
        raise ValueError(f"Reconstructed behavior log probability differs by {max_gap}")
    return examples, max_gap


def consistency(states, model, encoder):
    records = []
    weights = np.r_[-1, 1 + .25 * model.fractions.numpy()]
    for offset in range(0, len(states), 64):
        chunk = states[offset:offset+64]
        values = score_public(model, encoder, [state for _, _, state, _ in chunk])
        for (identifier, step, _, policy), value in zip(chunk, values, strict=True):
            q = np.asarray([action["probability"] for action in value["q"]])
            mixture = policy @ q
            difference = mixture - value["v"]
            records.append(dict(id=identifier, step=step, death=float(difference[0]),
                                utility=float(difference @ weights), tv=float(abs(difference).sum() / 2)))
    result = {}
    for key in ("death", "utility", "tv"):
        values = np.asarray([row[key] for row in records])
        mean = values.mean()
        interval = 1.96 * values.std(ddof=1) / np.sqrt(len(values))
        result[key] = dict(mean=float(mean), trajectory_ci95=[float(mean-interval), float(mean+interval)])
    return dict(rows=records, metrics=result)


def run(output, weights, count):
    os.chdir(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    cfg = config()
    runtime, _ = bind(output, Path(cfg["host"]))
    a2, _ = teacher(runtime, Path(cfg["teacher"]), 84)
    torch.manual_seed(runtime["p0"]["config"]()["initialization_seed"])
    P0 = runtime["v4"].Policy().eval()
    if runtime["digest"](runtime["v4"].checkpoint_policy(P0)) != SOURCE_HASHES[0]:
        raise ValueError("P0 initialization identity mismatch")
    _, saved = load(weights[0])
    encoder = Encoder(saved["vocabulary"])
    inputs, errors = {}, {}
    for i, (name, path, behavior) in enumerate([("P0", "p0", P0), ("A2", "teacher", a2)]):
        inputs[name], errors[name] = sample(runtime, behavior, Path(cfg["sources"][path]),
                                            encoder, 71393111+i, count, i)
    report = {}
    for checkpoint in weights:
        net, payload = load(checkpoint)
        if payload["vocabulary"] != saved["vocabulary"] or payload["policies"] != saved["policies"]:
            raise ValueError("Mismatched consistency checkpoint semantics")
        report[checkpoint.parent.name] = dict(checkpoint=checksum(checkpoint),
            policies={name: consistency(states, net, encoder) for name, states in inputs.items()})
    write_json(output / "summary.json", dict(models=report, max_logp_replay_error=errors, per_policy=count))
    print(errors, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    cli.add_argument("checkpoints", nargs="+", type=Path)
    cli.add_argument("--count", type=int, default=256)
    args = cli.parse_args()
    run(args.output.resolve(), [path.resolve() for path in args.checkpoints], args.count)
