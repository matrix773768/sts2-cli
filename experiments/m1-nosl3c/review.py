"""Small checkpoint reports from validated public rows and timing summaries."""
from collections import Counter
import gzip
import json

from analyze import estimate
from audit_value import hp_calibration
from journal import atomic_bytes
from nosl_experience import json_bytes, save_json
from nosl_run import quantiles


def performance(batches):
    clocks = [b["timing"] for b in batches]
    episodes = [r for b in batches for r in b["rows"]]
    phases = ("features_ms", "forward_ms", "memory_choice_ms", "rpc_ms", "engine_replay_ms",
              "engine_observe_ms", "reset_ms")
    return dict(root_count=len(batches), resident_roots=sum(t["resident"] for t in clocks),
                build_ms=quantiles([t["initialize_ms"] for t in clocks]),
                capture_ms=quantiles([t["snapshot_ms"] for t in clocks]),
                wall_root_ms=quantiles([t["total_ms"] for t in clocks]),
                startup_ms=quantiles([t["startup_ms"] for t in clocks if t["startup_ms"]]),
                model_init_ms=quantiles([t["build_phases"]["model_init"] for t in clocks
                                         if t.get("build_phases", {}).get("model_init")]),
                retire_ms=quantiles([t["retirement_ms"] for t in clocks if "retirement_ms" in t]),
                retirement=dict(Counter(t["retirement"] for t in clocks)),
                cache_hits=sum(t.get("cache_hits", 0) for t in clocks),
                lease_recycles=sum(t.get("lease_recycled", False) for t in clocks),
                episode_phase_ms={k: quantiles([r["timing"][k] for r in episodes if "timing" in r]) for k in phases})


def metric(rows):
    raw = estimate(rows)
    selected = {k: v for k, v in raw.items() if k not in ("raw_win_hp", "joint_stocked")}
    selected["win_hp"] = quantiles(raw["raw_win_hp"])
    behavior = Counter(s["action"]["kind"] for r in rows for s in r["transitions"])
    selected["behavior"] = dict(behavior)
    selected["values"]["hp_calibration"] = hp_calibration(rows)
    selected["failure_reasons"] = dict(Counter(r["feedback"]["reason"] for r in rows if r["feedback"]["reason"]))
    return selected


def training_summary(batches, collect_s, optimize, writes_s):
    rows = [r for b in batches for r in b["rows"]]
    by_family = {}
    for row in rows:
        counts = by_family.setdefault(row["group"], dict(roots=set(), attempted=0, qualified=0))
        counts["roots"].add(row["root"])
        counts["attempted"] += 1
        counts["qualified"] += row["feedback"]["eligible"]
    for counts in by_family.values():
        counts["roots"] = len(counts["roots"])
    return dict(metric=metric(rows), performance=performance(batches), families=by_family,
                roots_constructed=sum(not all(r["feedback"]["reason"] == "root_generation_failed" for r in b["rows"])
                                      for b in batches),
                roots_qualified=sum(any(r["feedback"]["eligible"] for r in b["rows"]) for b in batches),
                collect_seconds=collect_s, audit_ledger_write_seconds=writes_s, optimizer=optimize)


def compare(previous, mode, current):
    if not previous:
        return None
    older = previous["selection"][mode]
    return dict(win_per_attempt=current["wins_per_attempt"] - older["wins_per_attempt"],
                weighted_hp=current["weighted_hp"] - older["weighted_hp"]
                if current["weighted_hp"] is not None and older["weighted_hp"] is not None else None)


def reviews(output):
    paths = sorted((output / "reviews").glob("u*/review-summary.json"))
    return [json.loads(path.read_bytes()) for path in paths]


def publish(output, store, config, step, model_hash, selection, report=None):
    history = reviews(output)
    same_step = next((s for s in history if s["update"] == step), None)
    if same_step:
        if same_step["model_sha256"] != model_hash:
            raise ValueError("Review model hash differs from its checkpoint")
        return same_step
    metrics = [store.load(u)[1] for u in range(1, step + 1)]
    count = Counter()
    coverage = {}
    for m in metrics:
        count.update(m["metric"]["statuses"])
        for recipe, family in m["families"].items():
            current = coverage.setdefault(recipe, Counter())
            current.update(family)
    n = sum(count.values())
    qualified = count["predicted_win"] + count["death"]
    cumulative = dict(attempts=n, qualified=qualified, independent_roots=step * config["roots_per_update"],
                      statuses=count, by_family=coverage,
                      collect_seconds=sum(m["collect_seconds"] for m in metrics),
                      optimizer_seconds=sum(m["optimizer"]["seconds"] for m in metrics))
    cumulative["root_reuses"] = n - cumulative["independent_roots"]
    cumulative["roots_constructed"] = sum(m["roots_constructed"] for m in metrics)
    cumulative["roots_qualified"] = sum(m["roots_qualified"] for m in metrics)
    cumulative["attempts_per_collection_second"] = n / cumulative["collect_seconds"] if n else None
    timers = [(output / "checkpoint-timings" / f"u{u:06d}.json") for u in range(1, step + 1)]
    cumulative["checkpoint_seconds"] = sum(json.loads(p.read_bytes())["seconds"] for p in timers if p.exists())
    summary = dict(schema="sts2.nosl3c.review.v1", update=step, model_sha256=model_hash,
                   cumulative=cumulative, latest_batch=metrics[-1] if metrics else None,
                   selection=selection, final_report=report,
                   compare_selection={mode: compare(history[-1] if history else None, mode, m)
                                      for mode, m in selection.items()},
                   recent_curve=[dict(update=s["update"], train=s["cumulative"]["attempts"],
                                      sample=s["selection"]["sample"]["wins_per_attempt"],
                                      greedy=s["selection"]["greedy"]["wins_per_attempt"])
                                 for s in history[-7:]],
                   alerts=[f"{mode}: {m['attempts'] - m['eligible']} unqualified"
                           for mode, m in selection.items() if m["eligible"] < m["attempts"]])
    if metrics and metrics[-1]["metric"]["eligible"] < metrics[-1]["metric"]["attempts"]:
        summary["alerts"].append(f"training: {metrics[-1]['metric']['failure_reasons']}")
    for mode, delta in summary["compare_selection"].items():
        if delta and abs(delta["win_per_attempt"]) >= .25:
            summary["alerts"].append(f"{mode}: |delta win rate| >= 0.25")
    folder = output / "reviews" / f"u{step:06d}"
    folder.mkdir(parents=True, exist_ok=True)
    write_markdown(folder / "review-summary.md", summary)
    save_json(folder / "review-summary.json", summary)
    save_json(output / "review-summary.json", summary)
    write_markdown(output / "review-summary.md", summary)
    return summary


def write_markdown(target, s):
    c = s["cumulative"]
    lines = [f"# NOSL3C 更新 {s['update']}", "", f"模型 SHA-256 `{s['model_sha256']}`", "",
             f"累计 {c['attempts']} 次训练尝试，{c['independent_roots']} 个独立根，{c['qualified']} 条合格轨迹。",
             f"胜 {c['statuses'].get('predicted_win', 0)}，死 {c['statuses'].get('death', 0)}。",
             "", "| 评价池 | 模式 | 胜／尝试 | 合格 | 胜局平均 HP |",
             "| --- | --- | ---: | ---: | ---: |"]
    for group, values in (("选择", s["selection"]), ("最终报告", s["final_report"] or {})):
        for mode, m in values.items():
            lines.append(f"| {group} | {mode} | {m['wins']}/{m['attempts']} | {m['eligible']} | {m['win_hp_mean']} |")
    lines.extend(["", "机器摘要包含动作分布、初始价值校准、分阶段成本、资格、梯度、优势及与上一检查点的差值。"])
    if s["alerts"]:
        lines.extend(["", "本期异常提示", "", *[f"- {alert}" for alert in s["alerts"]]])
    atomic_bytes(target, ("\n".join(lines) + "\n").encode("utf-8"))


def export_public(output, store):
    path = output / "public.jsonl.gz"
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as stream, gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as archive:
        for phase in ("train", "selection", "report"):
            for row in store.rows(phase):
                archive.write(json_bytes(row) + b"\n")
    tmp.replace(path)