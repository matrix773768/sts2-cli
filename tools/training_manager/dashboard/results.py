"""Read measured training and development metrics from approved artifacts."""

import re

from .backend import DC1, INITIAL, CURRICULUM, NIGHT, NIGHT_HF1, contained
from ..common import read


def load(base, file, default=None):
    return read(contained(base, base / file), default)


def weighted(rows, field, denominator):
    valid = [row for row in rows if row.get(field) is not None and row.get(denominator)]
    total = sum(row[denominator] for row in valid)
    return sum(row[field] * row[denominator] for row in valid) / total if total else None


def training(output, stage, progress):
    out = contained(output, output / stage)
    limit = (progress or {}).get("done", 0)
    curve = []
    for path in sorted(out.glob("update-*.json")):
        match = re.fullmatch(r"update-(\d+)\.json", path.name)
        if not match or int(match[1]) > limit:
            continue
        data = load(out, path.name)
        groups = data["validation"]
        values = list(groups.values())
        curve.append(dict(updates=int(match[1]), loss=data["loss"], nll=weighted(values,"nll","n"),
                          brier=weighted(values,"brier","n"), mae=weighted(values,"mae","wins"),
                          hp=groups))
    return curve


def development(output, stage):
    summary = load(output, f"{stage}/ledger/summary.json") or load(output, f"{stage}/battle/summary.json")
    if not summary:
        return None
    by_hp = load(output, f"{stage}/metrics.json", {})
    strata = [group for group in by_hp.values() if group.get("attempts")]
    low = weighted([s | {"low": s.get("win_at_or_below", {}).get("10")} for s in strata], "low", "attempts")
    return dict(attempts=summary["attempts"], complete=summary["complete"], win=summary["win_rate"],
                net=(weighted(strata, "mean_net", "complete") if strata else summary.get("net_loss_mean")),
                zero=weighted(strata, "zero_net_win", "attempts"), low=low,
                seconds=summary.get("wall_s"), hp=by_hp)


def production(output, name):
    summary = load(output, f"{name}/ledger/summary.json") or load(output, f"{name}/battle/summary.json")
    if not summary:
        return None
    manifest = load(output, f"{name}/roots.json", {})
    levels = {}
    for _, spec, _, family, _ in manifest.get("jobs", []):
        levels.setdefault(spec["max_hp"], set()).add(family)
    return {key: summary.get(key) for key in ("attempts","complete","wall_s")} | {
        "diagnostics": len(manifest["diagnostic"]) if "diagnostic" in manifest else None,
        "scheduled_families_by_hp": {key: len(value) for key,value in levels.items()},
        "categories": manifest.get("categories"),
        "promotion": load(output, f"{name}/promotion.json")}


def stage_seconds(report, stage):
    completed = [run for run in report["runs"] if run["stage"] == stage and run["outcome"]]
    return sum(run["outcome"]["ended"] - run["outcome"]["started"] for run in completed) if completed else None


def result_row(output, report, label, fit, dev, complex_stage=None, production_stages=()):
    progress = report["stages"].get(fit)
    completed = {run["stage"] for run in report["runs"] if run["outcome"]
                 and run["outcome"]["state"] == "completed"}
    return dict(name=label, id=report["id"], development=development(output, dev) if dev in completed else None,
                complex=development(output, complex_stage) if complex_stage in completed else None,
                training=training(output, fit, progress),
                updates=progress.get("updates", progress.get("done")) if progress else None,
                training_seconds=stage_seconds(report,fit),
                production={stage: item for stage in production_stages
                            if stage in completed and (item := production(output,stage))})


def results(backend, manager):
    reports = {row["id"]: manager.report(row, persist=False) for row in manager.rows()
               if row["id"] in (INITIAL, CURRICULUM, NIGHT, NIGHT_HF1) or row["id"].startswith((NIGHT+"-r",NIGHT_HF1+"-r"))
               or row["id"].endswith("smoke")}
    baseline = load(DC1, "results.json", {}).get("pools", {}).get("development", {})
    d2 = baseline.get("overall", {}).get("direct")
    baseline_summary = load(DC1, "evaluation/development/D2/summary.json", {})
    original = dict(attempts=d2["attempts"], complete=d2["complete"], win=d2["win_rate"],
                    net=d2["mean_net"], zero=d2["zero_net_win"], low=d2["win_at_or_below"]["10"],
                    seconds=baseline_summary.get("wall_s"),
                    hp={hp: info["direct"] for hp, info in baseline["by_max_hp"].items()}) if d2 else None
    initial = reports.get(INITIAL)
    curriculum = reports.get(CURRICULUM)
    rows = [dict(name="D2", development=original, training=[], complex=None, production={}, updates=None)]
    for label, report, fit, dev, complex_stage, prod in (
            ("G0-DC", initial, "initial", "development", "complex-development", ()),
            *((f"G{n}", curriculum, f"g{n}-fit", f"g{n}-development", f"g{n}-complex",
               (f"g{n}-direct", f"g{n}-search")) for n in (1,2,3))):
        rows.append(result_row(backend.home/"jobs"/report["id"], report, label, fit, dev, complex_stage, prod)
                    if report else dict(name=label, development=None, training=[], complex=None, production={}, updates=None))
    for key, report in reports.items():
        if key not in (NIGHT,NIGHT_HF1) and not key.startswith((NIGHT+"-r",NIGHT_HF1+"-r")):
            continue
        output=backend.home/"jobs"/key
        for n in range(1,13):
            prefix=f"g{n}"
            audit=load(output,f"{prefix}-audit/summary.json",{})
            if audit.get("complete"):
                row=result_row(output,report,f"{key} G{n}",f"{prefix}-fit",f"{prefix}-development",
                               f"{prefix}-complex",(f"{prefix}-direct",f"{prefix}-search"))
                rows.append(row)
    gate = load(backend.home/"jobs"/INITIAL, "gate/gate.json") if initial else None
    smoke = []
    for key, report in reports.items():
        if not key.endswith("smoke"):
            continue
        available = set(report["stages"])
        dev = "development"
        fit = "training"
        output = backend.home/"jobs"/key
        item = result_row(output, report, key, fit, dev, production_stages=("experience",) if "experience" in available else ())
        smoke.append(item)
    return dict(formal=rows, smoke=smoke, gate=gate, markdown=markdown(rows,smoke,gate))


def markdown(rows, smoke, gate):
    def fmt(value, percent=False):
        if value is None:
            return "尚未生成"
        return f"{value:.1%}" if percent else f"{value:.4g}"

    lines = ["# DC2B 实验摘要", "", "开发集读数来自本地实验产物。", "",
             "| 模型 | 开发尝试 | 胜率 | 平均净战损 | 零净战损胜率 | ≤10 HP 净战损胜率 | 更新 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        dev = row["development"] or {}
        values = [fmt(dev.get(key), key in ("win","zero","low")) for key in
                  ("attempts","win","net","zero","low")]
        lines.append("| " + " | ".join([row["name"], *values, fmt(row["updates"])]) + " |")
    lines.extend(["", "## 开发退化检查", "", "尚未生成" if not gate else ("通过" if gate["passed"] else "未通过")])
    if gate:
        comparison = gate["comparison"]
        lines.append(f"- 配对 {comparison['paired']}，共同完整 {comparison['joint_complete']}，"
                     f"胜率变化 {comparison['win_delta']:+.2%}，死亡率变化 {comparison['death_delta']:+.2%}")
    for row in rows + smoke:
        if row["training"]:
            final = row["training"][-1]
            lines.extend(["", f"## {row['name']} 最后已提交更新", "",
                          f"- 更新 {final['updates']}，训练损失 {fmt(final['loss'])}，验证 NLL {fmt(final['nll'])}。"])
            for hp, values in final["hp"].items():
                lines.append(f"- {hp} HP 验证样本 {values['n']}，死亡 Brier {fmt(values['brier'])}，"
                             f"绝对净战损 MAE {fmt(values['mae'])} HP")
        for stage, item in row["production"].items():
            lines.append(f"- {row['name']} {stage} 经验 {item['complete']}/{item['attempts']}（完整/尝试）")
    if smoke:
        lines.extend(["", "## 隔离验收任务", ""])
        for row in smoke:
            dev = row["development"] or {}
            lines.append(f"- {row['name']}，更新 {fmt(row['updates'])}，开发尝试 {fmt(dev.get('attempts'))}")
    return "\n".join(lines) + "\n"
