"""Projection of the INF1 queue, reviewable plans and admitted artifacts."""

import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from threading import Lock
from time import monotonic, time

from ..common import (HOME, MODES, ROOT, checksum, freeze, identifier, input_path, output_for,
                      read, settings, validate_settings, write)
from ..ledger import identity as ledger_identity
from ..manager import ACTIVE, Manager
from ..windows import cpu_times, process_identity, resources
from ..recovery import approve, offer
from ..timing import CONTINUATION_JOB, incident_status


CONFIGS = ROOT / "configs/training_jobs"
DC1 = ROOT / "logs/m1-dc1-formal"
INITIAL = "dc2b-initial"
CURRICULUM = "dc2b-curriculum"
NIGHT = "dc2b-night1"
NIGHT_HF1 = "dc2b-night1-hf1"
SETTABLE = ("idle_seconds", "min_disk_mb", "min_ram_mb", "min_vram_mb", "resource_samples", "require_ac")
NAMES = {
    INITIAL: ("DC2B 初始训练", "从 D2 迁移价值网络，完成原开发集退化检查及复杂构筑对照。"),
    CURRICULUM: ("DC2B 课程训练", "最多三代，逐代生产经验、构建特征、训练并运行开发评测。"),
    NIGHT_HF1: ("DC2B 八小时夜间训练 HF1", "修复版，使用独立输出目录与种子命名空间。"),
    NIGHT: ("DC2B 八小时夜间训练", "八小时总计算预算，最多十二代；逐代审计并保留可恢复体验。"),
    "sts2-smoke": ("STS2 小规模验收", "运行有限经验生产、特征构建、续训和开发评测。"),
    "inf2-smoke": ("INF2 面板验收", "隔离运行 80 次 CUDA 更新和 8 个开发根。"),
}


def contained(base, path):
    """Disallow traversal and any path redirected via symlink or Windows junction."""
    if ".." in path.parts or not path.is_relative_to(base) or path.resolve() != path or base.resolve() != base:
        raise ValueError("此路径不在已审核的目录内")
    return path


def review_gate(manager):
    try:
        row = manager.job(INITIAL)
    except ValueError:
        return "初始训练尚未提交"
    if row["state"] != "completed":
        return f"初始训练尚未成功完成（{row['state']}，{row['reason'] or '等待完整产物'}）"
    try:
        spec, output, _, _ = manager.inspect(row)
        contained(manager.home / "jobs", output)
        if read(contained(output, output / "task.json")) != spec:
            return "初始任务输出身份与队列不一致"
        gate = read(contained(output, output / "gate/gate.json"))
        if not gate:
            return "缺少初始任务的 gate.json"
        if gate.get("passed") is not True:
            return "初始训练的开发退化检查未通过"
        report = manager.report(row, persist=False)
        completed = {run["stage"] for run in report["runs"] if run["outcome"]
                     and run["outcome"]["state"] == "completed" and run["outcome"]["exit_code"] == 0}
        if not {stage["id"] for stage in spec["stages"]} <= completed or not {
                "initial", "development", "gate", "complex-baseline", "complex-development"} <= completed:
            return "队列中缺少完整的初始训练和开发评测退出记录"
        comparison = gate["comparison"]
        if (comparison["paired"] != 512 or comparison["joint_complete"] < .98 * 512
                or not -.05 <= comparison["win_delta"] <= 1 or not -1 <= comparison["death_delta"] <= .05):
            return "实际开发对照数据未达到退化门槛"
        model = checksum(contained(output, output / "initial/best.pt"))
        candidate = ledger_identity(contained(output, output / "development/ledger/results.sqlite"))
        reference = ledger_identity(contained(DC1, DC1 / "evaluation/development/D2/results.sqlite"))
        if (candidate["model"] != model or candidate["manifest"] != reference["manifest"]
                or candidate["count"] != 512 or reference["count"] != 512
                or candidate["purpose"] != reference["purpose"] or candidate["purpose"] != "development"):
            return "初始模型、开发账本或配对开发队列身份不一致"
        if gate.get("evidence") != {"candidate": candidate, "reference": reference}:
            return "gate.json 未绑定当前模型的实际开发账本"
        for name in ("complex-baseline", "complex-development"):
            item = ledger_identity(contained(output, output / name / "ledger/results.sqlite"))
            expected_model = model if name == "complex-development" else reference["model"]
            if item["purpose"] != "complex_development" or not item["count"] or item["model"] != expected_model:
                return "复杂构筑开发对照产物缺失或身份不匹配"
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        return f"初始训练准入证据不可用：{error}"
    return None


class Backend:
    def __init__(self, home, templates=CONFIGS):
        self.home, self.templates = home, templates
        self.lock = Lock()
        self.drafts = {}
        self.last_probe = (0, None)
        self.cpu = cpu_times()

    def plans(self, manager):
        items = []
        files = sorted(self.templates.glob("*.json"), key=lambda p: (
            [INITIAL, CURRICULUM, NIGHT, NIGHT_HF1].index(p.stem) if p.stem in (INITIAL, CURRICULUM, NIGHT, NIGHT_HF1) else 4, p.name))
        for path in files:
            contained(self.templates, path)
            spec = read(path, {})
            if not isinstance(spec, dict) or not {"stages", "id", "python", "output", "inputs"} <= spec.keys():
                continue
            if path.stem != spec["id"]:
                continue
            if self.home != HOME and spec["id"] in (INITIAL, CURRICULUM, NIGHT, NIGHT_HF1):
                continue
            if self.home != HOME:
                spec = spec | {"output": (self.home / "jobs" / identifier(spec["id"])).relative_to(ROOT).as_posix()}
            items.append(self.plan(manager, spec))
        if self.home == HOME and self.templates == CONFIGS:
            try:
                recovery = offer(manager)
                if recovery:
                    spec, proof = recovery
                    item = self.plan(manager, spec)
                    item.update(purpose="按审计证据续接 G3；独立批准新预算后才能提交。",
                                recovery={key: proof[key] for key in ("timing","g3","models","completed")})
                    items.append(item)
            except (OSError, ValueError, KeyError, TypeError) as error:
                spec = dict(id=CONTINUATION_JOB, output=f"logs/inf1/jobs/{CONTINUATION_JOB}", stages=[], inputs=[])
                items.append(dict(spec=spec, name="DC2B 夜间任务 G3 续接", purpose="原任务的审计校验未通过。",
                                  reasons=[str(error)], missing=[], asset_count=0))
        return items

    def plan(self, manager, spec):
        key = spec["id"]
        name, purpose = NAMES.get(key, (spec["name"], spec["type"]))
        output = output_for(self.home, spec)
        paths = sorted(set(spec["inputs"]) | {spec["python"]} | {stage["args"][0] for stage in spec["stages"]}
                       | {stage["light_args"][0] for stage in spec["stages"] if "light_args" in stage})
        missing = [path for path in paths if not input_path(spec, path).is_file()]
        already = any(row["id"] == key for row in manager.rows())
        reasons = []
        if already:
            reasons.append("任务 ID 已提交")
        elif output.exists():
            reasons.append("输出目录已经存在，请保留原实验资产")
        if key in (CURRICULUM, NIGHT, NIGHT_HF1):
            blocked = review_gate(manager)
            if blocked:
                reasons.append(blocked)
        if missing:
            reasons.append(f"缺少 {len(missing)} 项输入资产")
        return dict(spec=spec, name=name, purpose=purpose, missing=missing, asset_count=len(paths), reasons=reasons)

    def overview(self, manager):
        cfg = settings(self.home)
        owner = read(self.home / "manager.json")
        online = bool(owner and process_identity(owner["pid"]) == owner)
        tasks = []
        for row in manager.rows():
            spec, output, stage, work = manager.inspect(row)
            progress = read(work / "progress.json") if work else None
            if progress and progress.get("checkpoint"):
                try:
                    source = contained(work, (work / progress["checkpoint"]))
                    progress["checkpoint"] = source.relative_to(ROOT).as_posix() if source.is_file() else None
                except ValueError:
                    progress["checkpoint"] = None
            timing = manager.timing(row, spec, output)
            proof, blocker = incident_status(row, output, spec)
            if progress and proof:
                committed = proof["g3"]["identity"]["count"]
                progress |= {"done":committed, "attempts":committed, "complete":committed, "throughput":None}
            task = {field: row[field] for field in ("id", "state", "intent", "reason", "retries", "errors")}
            task.update(name=NAMES.get(row["id"], (spec["name"], ""))[0], output=output.relative_to(ROOT).as_posix(),
                        stage=stage["id"] if stage else None, stage_index=row["stage"], stage_total=len(spec["stages"]),
                        boundary=stage["boundary"] if stage else None, progress=progress,
                        seconds=timing["confirmed_seconds"], timing=timing, audit_blocker=blocker,
                        paused_seconds=row["paused_seconds"] + (max(0,time()-row["paused_at"]) if row["paused_at"] else 0),
                        budget=spec.get("budget_seconds"), retryable=bool(
                            row["state"] in ("failed", "interrupted") and row["retries"] < spec["max_retries"]
                            and not ("budget_seconds" in spec and manager.has_interruption(row))
                            and (not row["token"] or stage["resume"] != "none")))
            tasks.append(task)
        return dict(online=online, enabled=manager.get_control("enabled", cfg["enabled"]),
                    closing=bool(online and manager.get_control("halt")), mode=manager.get_control("mode", cfg["mode"]),
                    tasks=tasks)

    def probe(self):
        with self.lock:
            now = monotonic()
            if now - self.last_probe[0] >= 3 or self.last_probe[1] is None:
                sample = resources(self.home, gpu=True)
                cpu = cpu_times()
                rate = None
                if cpu and self.cpu and cpu[1] > self.cpu[1]:
                    rate = 100 * (1 - (cpu[0] - self.cpu[0]) / (cpu[1] - self.cpu[1]))
                self.cpu = cpu
                self.last_probe = now, sample | {"cpu_pct": rate if rate is None else min(100, max(0, rate))}
            return self.last_probe[1] | {"settings": {key: settings(self.home)[key] for key in SETTABLE}}

    def action(self, manager, operation, data, session):
        with self.lock:
            if operation == "freeze":
                item = self.allowed_plan(manager, data["id"])
                prepared = approve(manager, data.get("budget_seconds")) if item.get("recovery") else item["spec"]
                frozen = freeze(prepared, self.home)
                token = secrets.token_urlsafe(24)
                now = monotonic()
                self.drafts = {k: v for k, v in self.drafts.items() if now - v[2] < 1800}
                if len(self.drafts) >= 64:
                    self.drafts.pop(next(iter(self.drafts)))
                self.drafts[token] = session, frozen, now, item["spec"]
                return {"draft": token, "spec": frozen}
            if operation == "submit":
                owner, frozen, created, template = self.drafts.get(data["draft"], (None, None, 0, None))
                if owner != session or monotonic() - created >= 1800 or frozen["sha256"] != data["sha256"]:
                    raise ValueError("冻结凭据已失效，请重新审核")
                item = self.allowed_plan(manager, frozen["id"])
                if template != item["spec"]:
                    raise ValueError("计划模板已经改变，请重新冻结")
                if item.get("recovery"):
                    approve(manager, frozen["budget_seconds"])
                manager.submit(frozen)
                del self.drafts[data["draft"]]
                return {"id": frozen["id"], "state": "queued"}
            if operation in ("pause", "resume", "cancel", "force", "retry"):
                key = identifier(data["id"])
                manager.request(key, operation)
                return {"id": key, "state": manager.job(key)["state"]}
            if operation in ("stop-all", "shutdown"):
                manager.stop(shutdown=operation == "shutdown")
            elif operation == "enable":
                if manager.get_control("halt") and self.overview(manager)["online"]:
                    raise ValueError("管理器正在安全关闭，请等它退出再启动")
                manager.control("enabled", True)
            elif operation == "mode":
                if data["mode"] not in MODES:
                    raise ValueError("请选择有效的运行模式")
                manager.control("mode", data["mode"])
            elif operation == "settings":
                if not data or not set(data) <= set(SETTABLE):
                    raise ValueError("设置包含不支持的项目")
                user = read(self.home / "settings.json", {}) | data
                validate_settings(settings(self.home) | data)
                write(self.home / "settings.json", user)
            elif operation == "start":
                if not self.overview(manager)["online"]:
                    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "tools.training_manager",
                                             "--home", str(self.home.relative_to(HOME)), "start"],
                                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise ValueError(result.stderr.strip() or "INF1 启动失败")
            elif operation == "folder":
                _, output, _, _ = manager.inspect(manager.job(identifier(data["id"])))
                os.startfile(contained(self.home / "jobs", output))
            else:
                raise ValueError("不支持的控制操作")
            return self.overview(manager)

    def allowed_plan(self, manager, key):
        item = next((item for item in self.plans(manager) if item["spec"]["id"] == key), None)
        if not item:
            raise ValueError("未找到仓库配置")
        if item["reasons"]:
            raise ValueError("；".join(item["reasons"]))
        return item

    def details(self, manager, key):
        row = manager.job(identifier(key))
        spec, output, _, _ = manager.inspect(row)
        report = manager.report(row, persist=False)
        _, blocker = incident_status(row, output, spec)
        return report | {"files": self.job_files(output, spec, report), "audit_blocker": blocker}

    def job_files(self, output, spec, report):
        contained(self.home / "jobs", output)
        files = {"task.json", "report.json"}
        for run in report["runs"]:
            for stream in ("stdout", "stderr"):
                path = Path(run[stream])
                files.add(path.relative_to(output).as_posix())
        completed = {run["stage"] for run in report["runs"] if run["outcome"]
                     and run["outcome"]["state"] == "completed"}
        for stage in spec["stages"]:
            name = stage["id"]
            files.update(f"{name}/{file}" for file in ("progress.json", "best.pt", "best-train.pt", "resume.pt"))
            if name in completed:
                files.update(f"{name}/{file}" for file in ("summary.json", "metrics.json", "gate.json",
                             "manifest.json", "promotion.json", "ledger/summary.json", "battle/summary.json"))
            work = contained(output, output / name)
            progress = read(contained(work, work / "progress.json"), {})
            if work.is_dir():
                for file in work.glob("update-*.json"):
                    if file.stem[7:].isdigit() and int(file.stem[7:]) <= progress.get("done", 0):
                        files.add(f"{name}/{file.name}")
        return [name for name in sorted(files) if contained(output, output / name).is_file()]

    def artifact(self, manager, key, name):
        row = manager.job(identifier(key))
        spec, output, _, _ = manager.inspect(row)
        if name not in self.job_files(output, spec, manager.report(row, persist=False)):
            raise ValueError("该文件不在任务可查看清单内")
        path = contained(output, output / name)
        if path.suffix not in (".json", ".log"):
            return dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size, content=None)
        maximum = 256 * 1024
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - maximum) if path.suffix == ".log" else 0)
            content = stream.read(maximum).decode("utf-8", errors="replace")
        return dict(path=path.relative_to(ROOT).as_posix(), bytes=size, content=content, truncated=size > maximum)
