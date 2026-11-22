"""Verify A2 ledgers and summarize training and paired evaluation without writes to them."""
from collections import Counter
from hashlib import sha256
import importlib.util
from math import sqrt
from pathlib import Path
from statistics import mean, median, pstdev
import sys

from curve import A1_HASH, UPDATES, a1, digest, load_step, manifests, p0, read, save, v4

spec = importlib.util.spec_from_file_location("a1_summary", a1.HERE / "summarize.py")
a1_summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a1_summary)
WIN = "admissible_predicted_win"
DEATH = "admissible_death"


def distribution(values):
    if not values:
        return dict(n=0)
    return dict(n=len(values), mean=mean(values), sd=pstdev(values), median=median(values),
                min=min(values), max=max(values))


def discrimination(wins, losses):
    if not wins or not losses:
        return None
    return sum((w > d) + 0.5 * (w == d) for w in wins for d in losses) / (len(wins) * len(losses))


def values(groups):
    result = {}
    for status, pairs in groups.items():
        predicted = [p for p, _ in pairs]
        actual = [r for _, r in pairs]
        errors = [p-r for p, r in pairs]
        result[status] = dict(predicted=distribution(predicted), actual=distribution(actual),
                              error=distribution(errors), mae=mean(map(abs, errors)) if errors else None,
                              rmse=sqrt(mean(e*e for e in errors)) if errors else None)
    result["win_death_auc"] = discrimination([p for p, _ in groups[WIN]], [p for p, _ in groups[DEATH]])
    return result


def cluster_key(evidence):
    failure = evidence.get("first_failure") or {}
    return " | ".join(str(field or "-") for field in
                      (evidence["status"], evidence.get("reason"), failure.get("effect"),
                       failure.get("card"), failure.get("action")))


def train_curve(out, batches, objective):
    training = out / "training"
    curves, clusters, examples = [], Counter(), {}
    with a1.readonly(training / "training.sqlite") as db:
        assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        steps = []
        for step, raw, stamp in db.execute("SELECT step,payload,sha FROM snapshots ORDER BY step"):
            assert sha256(raw).hexdigest() == stamp
            steps.append(step)
        assert steps == list(range(85))
        for step, roots in enumerate(batches):
            metric = read(training / f"metrics-{step+1:02d}.json")
            by_outcome = {WIN: [], DEATH: []}
            predictions, admissions, attempted = Counter(), Counter(), Counter()
            transitions = 0
            sql = ("SELECT root,rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                   "WHERE phase='train' AND step=? ORDER BY root")
            for (key, raw, stamp), root in zip(db.execute(sql, (step,)), roots, strict=True):
                assert sha256(raw).hexdigest() == stamp
                case = p0["unpack"](raw)
                assert case["spec"] == root
                audit = read(training / "audit" / f"{step:06d}-{key}.json")
                assert digest(audit) == case["evidence_sha256"]
                status = case["status"]
                attempted[status] += 1
                row = next(iter(case["rows"]), None)
                if row:
                    feedback = row["feedback"]
                    predictions[feedback["status"]] += 1
                    if feedback["eligible"]:
                        assert status in (WIN, DEATH) and audit["terminal_verified"]
                        reward = objective.reward(feedback, root["hp"])
                        by_outcome[status].append((row["transitions"][0]["value"], reward))
                        transitions += len(row["transitions"])
                        admissions[feedback["status"]] += 1
                if status not in (WIN, DEATH):
                    group = cluster_key(audit)
                    clusters[group] += 1
                    examples.setdefault(group, []).append(f"{step}:{key}")
            count = sum(admissions.values())
            assert count == metric["trained_rows"] == metric["stats"]["qualified"]
            assert transitions == metric["trained_transitions"] and attempted == metric["statuses"]
            curve = metric | dict(update=step+1, attempted=sum(attempted.values()), prediction=predictions,
                                  admitted_predictions=admissions, calibration=values(by_outcome))
            curve["main_wall_s"] = sum(metric[k] for k in ("collection_s", "optimizer_s", "sqlite_s"))
            curves.append(curve)
    totals = {k: sum(c[k] for c in curves) for k in (
        "attempted", "trained_rows", "trained_transitions", "host_starts", "main_wall_s",
        "collection_s", "optimizer_s", "sqlite_s", "audit_worker_s")}
    totals["cpu_s"] = sum(c["resources"]["cpu_s"] for c in curves)
    totals["phase_wall_s"] = sum(c["resources"]["wall_s"] for c in curves)
    totals["peak_mib"] = max(c["resources"]["sampled_peak_rss_mb"] for c in curves)
    for key in ("statuses", "prediction", "admitted_predictions"):
        totals[key] = sum((Counter(c[key]) for c in curves), Counter())
    return curves, totals, {k: dict(count=v, roots=examples[k]) for k, v in clusters.most_common()}


def main(out):
    cfg = read(out / "protocol.json")
    batches, roots = manifests(out)
    assert digest(batches) == cfg["train_sha256"] and digest(roots) == cfg["eval_sha256"]
    objective = v4.Objective(**cfg["config"]["objective"])
    curve, totals, clusters = train_curve(out, batches, objective)
    assert totals["attempted"] == 2016
    evaluations = {}
    evaluation_clusters, checkpoint_hashes = Counter(), {}
    for arm in ("sample", "greedy"):
        paired = {}
        for step in UPDATES:
            payload, stamp = load_step(out / "training/training.sqlite", step)
            if step == 12:
                assert payload["model_sha256"] == A1_HASH
            policy = v4.Policy()
            policy.load_state_dict(payload["model"])
            model_hash = digest(v4.checkpoint_policy(policy))
            assert model_hash == payload["model_sha256"]
            checkpoint_hashes[step] = dict(model=model_hash, snapshot=stamp)
            directory = out / f"eval-{step:02d}-{arm}"
            outcomes, metrics = a1_summary.evaluate(directory, objective, roots, cfg["evaluation_policy_seeds"],
                                                    model_hash, arm)
            groups = {status: [(x["root_value"], x["return_value"]) for x in outcomes if x["status"] == status]
                      for status in (WIN, DEATH)}
            metrics["value_diagnosis"] = values(groups)
            for i, outcome in enumerate(outcomes):
                if not outcome["eligible"]:
                    audit = read(directory / f"root-{i:03d}.json")["evidence"]
                    evaluation_clusters[cluster_key(audit)] += 1
            paired[step] = (outcomes, metrics)
        evaluations[arm] = [{
            "step": step, **metrics,
            "vs_initial": a1_summary.compare(paired[0][0], outcomes),
            "vs_previous": a1_summary.compare(paired[UPDATES[i-1]][0], outcomes) if i else None,
        } for i, (step, (outcomes, metrics)) in enumerate(paired.items())]
    exit_codes = Counter(str(read(file)["exit_code"]) for file in out.glob("*/engine/game-*/lifecycle.json"))
    save(out / "results.json", dict(train=totals, train_curve=curve, clusters=clusters,
                                   evaluation=evaluations, evaluation_clusters=evaluation_clusters,
                                   checkpoint_hashes=checkpoint_hashes, exit_codes=exit_codes))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
