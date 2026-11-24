"""Evaluate proper scores, calibration, support and pairing on frozen records."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from sv_data import checksum, write_json
from sv_model import load


def weighted(value, weight):
    return float(np.average(value, weights=weight)) if len(weight) and weight.sum() else None


def auc(score, positive, weight):
    if not positive.any() or positive.all():
        return None
    _, ids = np.unique(score, return_inverse=True)
    positives = np.bincount(ids, weights=weight * positive)
    negatives = np.bincount(ids, weights=weight * ~positive)
    return float((positives * (np.cumsum(negatives) - negatives / 2)).sum() /
                 (positives.sum() * negatives.sum()))


def calibration(p, actual, weight):
    groups = np.minimum((10 * p).astype(int), 9)
    bins = []
    for index in range(10):
        mask = groups == index
        w = weight[mask]
        bins.append(dict(p=weighted(p[mask], w), observed=weighted(actual[mask], w),
                         decisions=int(mask.sum()), mass=float(w.sum())))
    ece = sum(abs(row["p"] - row["observed"]) * row["mass"] for row in bins if row["mass"])
    return dict(ece=float(ece / weight.sum()), curve=bins)


def describe(data, name, mask, fractions):
    prob = data[name][mask]
    maximum = data[name + "_max"][mask]
    label, final, final_max = (data[field][mask] for field in ("cls", "final_hp", "final_max"))
    weight = data["weight"][mask]
    dead = label == 0
    win = ~dead
    death = prob[:, 0]
    points = maximum * fractions[None]
    cond = prob[:, 1:] / np.maximum(1 - death[:, None], 1.e-12)
    actual_hp_ratio = final / final_max
    cdf = np.cumsum(cond, axis=1)[:, :-1]
    crps = ((cdf - (fractions[None, :-1] >= actual_hp_ratio[:, None])) ** 2).mean(1)
    expected_hp = (prob[:, 1:] * points).sum(1)
    severe = final <= .5 * data["group"][mask, 3]
    severe_p = death + (prob[:, 1:] * (points <= .5 * data["group"][mask, 3, None])).sum(1)
    tail = dead | (actual_hp_ratio <= .2)
    tail_p = death + prob[:, 1:][:, fractions <= .2].sum(1)
    trajectories = len(np.unique(data["trajectory"][mask]))
    return dict(trajectories=trajectories, decisions=int(mask.sum()), sparse=trajectories < 100,
        death_n=int(dead.sum()), death_rate=weighted(dead, weight),
        nll=weighted(-np.log(prob[np.arange(len(prob)), label].clip(min=1.e-12)), weight),
        death_brier=weighted((death-dead)**2, weight), death_auc=auc(death, dead, weight),
        death_accuracy=weighted((death >= .5) == dead, weight), death_calibration=calibration(death, dead, weight),
        winning_fraction_crps=weighted(crps[win], weight[win]), expected_final_hp_mae=weighted(abs(expected_hp-final), weight),
        severe_brier=weighted((severe_p-severe)**2, weight), severe_calibration=calibration(severe_p, severe, weight),
        severe_auc=auc(severe_p, severe, weight), tail_brier=weighted((tail_p-tail)**2, weight),
        tail_calibration=calibration(tail_p, tail, weight))


def groupings(data, policies):
    g = data["group"]
    masks = {"all": np.ones(len(g), dtype=bool)}
    for idx, policy in enumerate(policies):
        masks[f"behavior={policy}"] = data["policy"] == idx
    for index, field, labels in ((0, "act", (1, 2, 3)), (1, "room", (0, 1, 2)),
                                 (2, "initial_hp", (80, 160, 999)), (9, "choice", (0, 1))):
        masks.update({f"{field}={label}": g[:, index] == label for label in labels})
    for field, counts, low, high in (
            ("current_hp_fraction", g[:, 3] / g[:, 4], .40, .8),
            ("turn", g[:, 5], 2, 6), ("hand", g[:, 6], 3, 6), ("energy", g[:, 7], 1, 3)):
        masks.update({f"{field}=low": counts < low, f"{field}=middle": (counts >= low) & (counts < high),
                      f"{field}=high": counts >= high})
    for label, bit in (("draw", 1), ("energy_gain", 2)):
        for flag in (0, 1):
            masks[f"{label}={flag}"] = ((g[:, 8] & bit) != 0) == bool(flag)
    return {label: mask for label, mask in masks.items() if mask.any()}


@torch.inference_mode()
def predictions(model, shards, device, batch):
    result = {}
    keys = ("cls", "final_hp", "final_max", "weight", "group", "trajectory", "policy", "old_logp")

    def keep(name, values):
        result.setdefault(name, []).append(values)

    for arrays in shards:
        for key in keys:
            keep(key, arrays[key])
        for start in range(0, len(arrays["cls"]), batch):
            b = {key: torch.from_numpy(value[start:start+batch]).to(device) for key, value in arrays.items()}
            for name, row in zip(("v", "q"), model(b, chosen_only=True), strict=True):
                logits, delta = model.split(row)
                keep(name, logits.softmax(-1).cpu().numpy())
                keep(name + "_max", (b["group"][:, 4, None] + 25 * delta).clamp_min(1).cpu().numpy())
    return {key: np.concatenate(series) for key, series in result.items()}


def consistency(data, fractions):
    trajectory, inverse = np.unique(data["trajectory"], return_inverse=True)
    scale = np.bincount(inverse, weights=data["weight"])
    support = np.r_[-1, 1 + .25 * fractions]
    offsets = {"death": data["q"][:, 0] - data["v"][:, 0],
               "expected_utility": (data["q"] - data["v"]) @ support}
    result = {}
    for key, offset in offsets.items():
        by_trajectory = np.bincount(inverse, weights=data["weight"] * offset) / scale
        mean = by_trajectory.mean()
        gap = 1.96 * by_trajectory.std(ddof=1) / np.sqrt(len(trajectory))
        result[key] = dict(q_observed_minus_v=float(mean), cluster_ci95=[float(mean-gap),float(mean+gap)])
    return result


def score(root, output, checkpoint, device):
    out = output / checkpoint.parent.name
    out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((root / "manifest.json").read_bytes())
    from train import load_shard
    shards = [load_shard(root, desc) for desc in manifest["shards"]["validation"]
              if checksum(root / desc["name"]) == desc["sha256"]]
    if len(shards) != len(manifest["shards"]["validation"]):
        raise ValueError("Validation shard identity mismatch")
    model, saved = load(checkpoint, device)
    fractions = model.fractions.cpu().numpy()
    data = predictions(model, shards, device, 512)
    grouped = groupings(data, saved["policies"])
    output = dict(checkpoint_sha256=checksum(checkpoint), epoch=saved["epoch"], data_sha256=checksum(root/"manifest.json"),
                  heads={name: {key: describe(data, name, mask, fractions) for key, mask in grouped.items()}
                         for name in ("v", "q")}, consistency=consistency(data, fractions))
    with (out / "validation.npz").open("wb") as stream:
        np.savez_compressed(stream, **data)
    write_json(out / "metrics.json", output)
    print(checkpoint.parent.name, {name: {k: output["heads"][name]["all"][k] for k in
          ("nll", "death_brier", "death_auc", "winning_fraction_crps", "expected_final_hp_mae")}
          for name in ("v", "q")}, flush=True)


def paired(eval_root, output):
    from sv_eval import load_rows
    results = {}
    for cohort in ("development", "confirmation"):
        directory = eval_root / cohort
        baseline = load_rows(directory / "a2")
        arms, retained = {}, {}
        for path in sorted(directory.iterdir()):
            if not (path / "summary.json").exists():
                continue
            data = load_rows(path)
            retained[path.name] = data
            if len(data) != len(baseline):
                raise ValueError("Incomplete paired comparison cohort")
            delta, loss, risk, failure_examples = [], [], [], []
            comparisons = {"loss_to_win": 0, "win_to_loss": 0, "joint_wins": 0}
            for ordinal, (item, base) in enumerate(zip(data, baseline, strict=True)):
                row, ref = item["row"], base["row"]
                if row["root"] != ref["root"]:
                    raise ValueError("Paired root recipe differs")
                win, bw = row["status"] == "predicted_win", ref["status"] == "predicted_win"
                delta.append(int(win) - int(bw))
                comparisons["loss_to_win"] += win and ref["status"] == "death"
                comparisons["win_to_loss"] += bw and row["status"] == "death"
                comparisons["joint_wins"] += win and bw
                diagnostic = item["diagnostics"]
                if win and bw:
                    loss.append(ref["terminal"]["hp"] - row["terminal"]["hp"])
                if row["complete"] and diagnostic:
                    risk.append((diagnostic[0]["death"], row["status"] == "death"))
                if bw and not win:
                    action, card = None, None
                    if row["steps"]:
                        step = row["steps"][0]
                        action = step["action"]["kind"]
                        slot = step["action"]["card"]
                        if slot is not None:
                            card = step["observation"]["hand"][slot]["id"]
                    failure_examples.append(dict(index=ordinal, status=row["status"], encounter=row["root"]["encounter"],
                        act=row["root"]["act"], hp=row["root"]["hp"], actions=row["length"],
                        initial_predicted_death=diagnostic[0]["death"] if diagnostic else None,
                        first_action=action, card=card))
            rng = np.random.default_rng(71393030)
            interval = np.quantile(rng.choice(delta, size=(3000, len(delta))).mean(1), [.025,.975]).tolist()
            arms[path.name] = dict(json.loads((path/"summary.json").read_bytes()) | comparisons,
                win_delta=float(np.mean(delta)), paired_root_bootstrap_ci95=interval,
                joint_win_loss_delta=float(np.mean(loss)) if loss else None,
                initial_predicted_death=float(np.mean([x[0] for x in risk])) if risk else None,
                actual_complete_death=float(np.mean([x[1] for x in risk])) if risk else None,
                examples=sorted(failure_examples, key=lambda x: x["initial_predicted_death"] or 0)[:8])
        for name in sorted(retained):
            base = name.removesuffix("-prior")
            if name == base or base not in retained:
                continue
            pairs = [(a["row"]["status"], b["row"]["status"])
                     for a,b in zip(retained[name], retained[base], strict=True)]
            arms[name]["versus_unconstrained"] = dict(death_to_win=sum(a == "predicted_win" and b == "death" for a,b in pairs),
                win_to_death=sum(a == "death" and b == "predicted_win" for a,b in pairs))
        results[cohort] = arms
    write_json(output, results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    calls = parser.add_subparsers(dest="command", required=True)
    validation = calls.add_parser("validation")
    validation.add_argument("data", type=Path)
    validation.add_argument("output", type=Path)
    validation.add_argument("checkpoints", type=Path, nargs="+")
    validation.add_argument("--device", default="cuda")
    battles = calls.add_parser("battles")
    battles.add_argument("evaluation", type=Path)
    battles.add_argument("output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    if args.command == "validation":
        for path in args.checkpoints:
            score(args.data, args.output, path, args.device)
    else:
        paired(args.evaluation, args.output)
