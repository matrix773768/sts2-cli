"""Read-only paired evaluation and gradient reconstruction for III-A5."""
from collections import Counter
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

from joint import A2, HERE, a1, cases, checkpoint_policy, digest, load_step, manifests, model_patch, p0, read, save, torch, v4


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


a3 = module("a3_gradient", HERE.parent / "m1-nosl3c-iii-a3/analyze.py")
eval_metrics = module("a1_eval", a1.HERE / "summarize.py")


def training(directory, batches):
    metrics = []
    with a1.readonly(directory / "training/training.sqlite") as db:
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        snapshots = list(db.execute("SELECT step,payload,sha FROM snapshots ORDER BY step"))
        assert [step for step, _, _ in snapshots] == list(range(37))
        for _, raw, stamp in snapshots:
            assert sha256(raw).hexdigest() == stamp
        for step, roots in enumerate(batches):
            tally = Counter()
            decisions, qualified = 0, 0
            query = ("SELECT rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                     "WHERE phase='train' AND step=? ORDER BY root")
            for (raw, stamp), root in zip(db.execute(query, (step,)), roots, strict=True):
                assert sha256(raw).hexdigest() == stamp
                batch = p0["unpack"](raw)
                assert batch["spec"] == root
                audit = read(directory / "training/audit" / f"{step:06d}-{batch['root']}.json")
                assert digest(audit) == batch["evidence_sha256"]
                tally[batch["status"]] += 1
                for row in batch["rows"]:
                    if row["feedback"]["eligible"]:
                        assert audit["terminal_verified"] and audit["native_terminal_stamp"]
                        decisions += len(row["transitions"])
                        qualified += 1
            metric = read(directory / "training" / f"metrics-{step+1:02d}.json")
            assert tally == metric["statuses"] and decisions == metric["trained_transitions"]
            assert qualified == metric["trained_rows"]
            metrics.append(metric)
    return metrics


def main(directory):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = read(directory / "protocol.json")
    cfg = protocol["config"]
    base_cfg = read(A2 / "protocol.json")["config"]
    seeds = protocol["evaluation_policy_seeds"]
    batches, roots = manifests(A2)
    assert digest(batches[:36]) == protocol["train_sha256"] and digest(roots) == protocol["eval_sha256"]
    assert not read(directory / "first-batch-gate.json")["differences"]
    curve = {"candidate": training(directory, batches[:36]),
             "baseline": [read(A2 / "training" / f"metrics-{step:02d}.json") for step in range(1, 37)]}
    outcomes = {}
    objective = v4.Objective(**cfg["objective"])
    for step in (12, 36):
        for mode in ("sample", "greedy"):
            name = f"eval-{step:02d}-{mode}"
            before, _ = load_step(A2 / "training/training.sqlite", step)
            after, _ = load_step(directory / "training/training.sqlite", step)
            left, base_metrics = eval_metrics.evaluate(A2 / name, objective, roots, seeds,
                                                       before["model_sha256"], mode)
            right, candidate_metrics = eval_metrics.evaluate(directory / name, objective, roots, seeds,
                                                             after["model_sha256"], mode)
            def outcome_auc(items):
                wins = [x["root_value"] for x in items if x["status"] == "admissible_predicted_win"]
                losses = [x["root_value"] for x in items if x["status"] == "admissible_death"]
                return (sum((w > d) + .5*(w == d) for w in wins for d in losses) / (len(wins)*len(losses))
                        if wins and losses else None)
            outcomes[name] = dict(baseline=base_metrics | {"auc": outcome_auc(left)},
                                  candidate=candidate_metrics | {"auc": outcome_auc(right)},
                                  paired=eval_metrics.compare(left, right))
    baseline_grads = [a3.measure(A2, step, base_cfg) for step in (1, 12, 36)]
    with model_patch():
        candidate_grads = [a3.measure(directory, step, cfg) for step in (1, 12, 36)]
    snapshots = {}
    for step in (0, 12, 36):
        payload, stamp = load_step(directory / "training/training.sqlite", step)
        policy = v4.Policy()
        policy.load_state_dict(payload["model"])
        assert digest(checkpoint_policy(policy)) == payload["model_sha256"]
        snapshots[step] = dict(model=payload["model_sha256"], snapshot=stamp)
    exits = Counter(str(read(path)["exit_code"]) for path in directory.glob("*/engine/game-*/lifecycle.json"))
    save(directory / "results.json", dict(curves=curve, evaluation=outcomes, snapshots=snapshots,
                                         gradients={"baseline": baseline_grads, "candidate": candidate_grads},
                                         exits=exits))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
