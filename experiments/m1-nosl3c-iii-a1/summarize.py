"""Summarize paired evaluation and verify the transactional training evidence."""
from collections import Counter
from hashlib import sha256
from math import sqrt
from pathlib import Path
from statistics import mean, median
import sys

from pilot import checkpoints, digest, p0, read, readonly, save, v4


def mean_or_none(values):
    return mean(values) if values else None


def evaluate(directory, objective, roots, seeds, model_hash, mode):
    outcomes = []
    for i, (root, seed) in enumerate(zip(roots, seeds, strict=True)):
        result = read(directory / f"root-{i:03d}.json")
        assert (result["root_index"], result["seed"], result["spec"]) == (i, seed, root)
        assert result["model_sha256"] == model_hash
        row = next(iter(result["rows"]), None)
        if row:
            assert row["mode"] == mode and row["split"] == "development-evaluation"
            assert row["behavior"] == {"seed": seed, "model_sha256": model_hash}
        feedback = row["feedback"] if row else {}
        status = result["status"]
        eligible = bool(feedback.get("eligible"))
        assert eligible == status.startswith("admissible_")
        assert not eligible or (result["evidence"]["terminal_verified"] and result["evidence"]["native_terminal_stamp"])
        outcome = dict(status=status, eligible=eligible)
        if row:
            outcome["root_value"] = row["transitions"][0]["value"] if row["transitions"] else None
            if eligible:
                final = feedback["observation"]
                outcome.update(return_value=objective.reward(feedback, root["hp"]),
                               hp_loss=max(0, root["hp"] - final["hp"]), turns=final["turn"])
        outcomes.append(outcome)
    assert Counter(item["status"] for item in outcomes) == read(directory / "summary.json")["statuses"]
    strict = [item for item in outcomes if item["eligible"]]
    wins = [item for item in strict if item["status"] == "admissible_predicted_win"]
    scored = [item for item in strict if item.get("root_value") is not None]
    errors = [item["root_value"] - item["return_value"] for item in scored]
    calibration = dict(n=len(errors), bias=mean_or_none(errors),
                       mae=mean_or_none([abs(x) for x in errors]),
                       rmse=sqrt(mean(x*x for x in errors)) if errors else None,
                       groups={status: dict(n=len(group), predicted=mean_or_none([x["root_value"] for x in group]),
                                           realized=mean_or_none([x["return_value"] for x in group]))
                               for status in ("admissible_predicted_win", "admissible_death")
                               for group in [[x for x in scored if x["status"] == status]]})
    return outcomes, dict(statuses=Counter(item["status"] for item in outcomes),
                          certified=len(strict), strict_wins=len(wins),
                          win_loss_mean=mean_or_none([item["hp_loss"] for item in wins]),
                          win_loss_median=median(item["hp_loss"] for item in wins) if wins else None,
                          win_turn_mean=mean_or_none([item["turns"] for item in wins]),
                          calibration=calibration, resources=read(directory / "summary.json")["resources"])


def compare(before, after):
    pairs = list(zip(before, after, strict=True))
    win = "admissible_predicted_win"
    both_win = [(a,b) for a,b in pairs if a["status"] == b["status"] == win]
    both_strict = [(a,b) for a,b in pairs if a["eligible"] and b["eligible"]]
    changes = Counter((a["status"], b["status"]) for a,b in pairs)
    return dict(
        gained_strict_win=sum(a["status"] != win and b["status"] == win for a,b in pairs),
        lost_strict_win=sum(a["status"] == win and b["status"] != win for a,b in pairs),
        common_strict=len(both_strict), common_wins=len(both_win),
        common_win_mean_loss_change=mean_or_none([b["hp_loss"]-a["hp_loss"] for a,b in both_win]),
        common_win_mean_turn_change=mean_or_none([b["turns"]-a["turns"] for a,b in both_win]),
        common_strict_mean_return_change=mean_or_none([b["return_value"]-a["return_value"] for a,b in both_strict]),
        common_strict_mean_value_change=mean_or_none([b["root_value"]-a["root_value"] for a,b in both_strict]),
        status_pairs={f"{a} -> {b}": n for (a,b),n in sorted(changes.items())},
    )


def training(directory, batches):
    updates = [read(directory / f"metrics-{step:02d}.json") for step in range(1, 13)]
    with readonly(directory / "training.sqlite") as db:
        for step, metrics in enumerate(updates):
            rows = db.execute("SELECT root,rows,sha FROM roots JOIN root_hashes USING (phase,step,root) "
                              "WHERE phase='train' AND step=? ORDER BY root", (step,))
            strict = []
            for (key, raw, stamp), root in zip(rows, batches[step], strict=True):
                assert sha256(raw).hexdigest() == stamp
                case = p0["unpack"](raw)
                assert case["spec"] == root
                audit = read(directory / "audit" / f"{step:06d}-{key}.json")
                assert digest(audit) == case["evidence_sha256"]
                strict.extend(row for row in case["rows"] if row["feedback"]["eligible"])
            assert len(strict) == metrics["trained_rows"] == metrics["stats"]["qualified"]
            assert sum(len(row["transitions"]) for row in strict) == metrics["trained_transitions"]
    totals = dict(collection_s=sum(x["collection_s"] for x in updates),
                  optimizer_s=sum(x["optimizer_s"] for x in updates),
                  sqlite_s=sum(x["sqlite_s"] for x in updates),
                  admitted=sum(x["trained_rows"] for x in updates),
                  transitions=sum(x["trained_transitions"] for x in updates),
                  cpu_s=sum(x["resources"]["cpu_s"] for x in updates),
                  peak_mib=max(x["resources"]["sampled_peak_rss_mb"] for x in updates),
                  host_starts=sum(x["host_starts"] for x in updates),
                  statuses=dict(sum((Counter(x["statuses"]) for x in updates), Counter())))
    totals["main_wall_s"] = sum(totals[k] for k in ("collection_s", "optimizer_s", "sqlite_s"))
    totals["qualified_per_s"] = totals["admitted"] / totals["main_wall_s"]
    return totals


def main(directory):
    protocol = read(directory / "protocol.json")
    batches = [[item["spec"] for item in batch]
               for batch in read(directory / "train-manifest/course-roots.json")]
    eval_batch, = read(directory / "eval-manifest/course-roots.json")
    roots = [item["spec"] for item in eval_batch]
    assert digest(batches) == protocol["train_sha256"] and digest(roots) == protocol["eval_sha256"]
    seeds = protocol["evaluation_policy_seeds"]
    objective = v4.Objective(**protocol["config"]["objective"])
    snapshots = {step: (stamp, digest(v4.checkpoint_policy(policy)))
                 for step, policy, stamp in checkpoints(directory / "training/training.sqlite")}
    assert snapshots[0][1] == "cb2130276dd73a62703a8a0b955b92809fdd7db3b23f8e10719f73d40a4006a9"
    result = dict(training=training(directory / "training", batches), snapshots=snapshots)
    for mode in ("sample", "greedy"):
        first, s0 = evaluate(directory / f"eval-00-{mode}", objective, roots, seeds, snapshots[0][1], mode)
        last, s12 = evaluate(directory / f"eval-12-{mode}", objective, roots, seeds, snapshots[12][1], mode)
        result[mode] = dict(update_0=s0, update_12=s12, paired=compare(first,last))
    save(directory / "results.json", result)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
