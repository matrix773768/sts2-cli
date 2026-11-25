"""Durable per-attempt timing. Wall timestamps are evidence, not duration clocks."""

import ctypes
import math
import os
from time import monotonic, time

from .common import ROOT, checksum, identity, read


HEARTBEAT_SECONDS = 2
INCIDENT = ROOT / "configs/training_jobs/inf3-night1-evidence.json"
INCIDENT_JOB = "dc2b-night1-hf1"
CONTINUATION_JOB = "dc2b-night1-hf1-r1"

if os.name == "nt":
    _unbiased = ctypes.WinDLL("kernel32", use_last_error=True).QueryUnbiasedInterruptTime
    _unbiased.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    _unbiased.restype = ctypes.c_int


def execution_clock():
    if os.name != "nt":
        return monotonic()
    ticks = ctypes.c_uint64()
    if not _unbiased(ctypes.byref(ticks)):
        raise ctypes.WinError(ctypes.get_last_error())
    return ticks.value / 10_000_000


def measured(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def heartbeat(attempt, owner):
    item = read(attempt / "heartbeat.json", {})
    if (owner and all(item.get(k) == owner.get(k) for k in ("token", "sha256", "process"))
            and measured(item.get("elapsed")) and measured(item.get("observed"))):
        return item
    return None


def duration(outcome):
    if measured(outcome.get("elapsed")):
        return outcome["elapsed"]
    if outcome["state"] == "interrupted":
        return 0
    return max(0, outcome["ended"] - outcome["started"])


def lost_attempt(run, owner, attempt):
    last = heartbeat(attempt, owner)
    return dict(state="interrupted", started=(owner or {}).get("started", run["launched"]),
                ended=last["observed"] if last else None, elapsed=last["elapsed"] if last else 0,
                last_confirmed=last["observed"] if last else None, detected=time(),
                exit_confirmed=False, unknown_tail=True, exit_code=None,
                reason="attempt exited without a result")


def verified_incident(row, output, spec):
    evidence = read(INCIDENT)
    if not evidence:
        raise ValueError("缺少 INF3 中断审计索引")
    if row["id"] != INCIDENT_JOB or evidence["source"] != row["id"] or evidence["key"] != CONTINUATION_JOB:
        raise ValueError("原任务或续接 ID 与审计索引不一致")
    if row["state"] != "interrupted":
        raise ValueError(f"原任务状态为 {row['state']}，审计要求 interrupted")
    if row["token"] != evidence["token"]:
        raise ValueError("原任务的中断令牌与审计索引不一致")
    if spec["sha256"] != evidence["task_sha256"] or identity(spec) != spec["sha256"]:
        raise ValueError("队列中的冻结任务身份与审计索引不一致")
    if read(output / "task.json") != spec:
        raise ValueError("原目录的 task.json 缺失或与队列冻结配置不一致")
    position = row["stage"]
    if (position != len(evidence["completed"]) or not 0 <= position < len(spec["stages"])
            or spec["stages"][position]["id"] != "g3-direct"):
        raise ValueError("队列的中断阶段与已审计的 G3 直接经验位置不一致")
    report = output / "report.json"
    if not report.is_file():
        raise ValueError("缺少原任务的 report.json")
    if checksum(report) != evidence["report_sha256"]:
        raise ValueError("原任务的 report.json SHA-256 与审计索引不一致，需独立复核差异")
    return evidence


def incident_status(row, output, spec):
    if row["id"] != INCIDENT_JOB:
        return None, None
    try:
        return verified_incident(row, output, spec), None
    except (OSError, ValueError, KeyError, TypeError) as error:
        return None, str(error)


def audited_timing(row, output, spec):
    evidence, _ = incident_status(row, output, spec)
    return evidence["timing"] if evidence else None
