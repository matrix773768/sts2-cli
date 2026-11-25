"""Durable per-attempt timing. Wall timestamps are evidence, not duration clocks."""

import ctypes
import math
import os
from time import monotonic, time

from .common import ROOT, checksum, read


HEARTBEAT_SECONDS = 2
INCIDENT = ROOT / "configs/training_jobs/inf3-night1-evidence.json"

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


def audited_timing(row, output, spec):
    if row["state"] != "interrupted" or row["id"] != "dc2b-night1-hf1":
        return None
    evidence = read(INCIDENT)
    if (evidence and spec["sha256"] == evidence["task_sha256"] and row["token"] == evidence["token"]
            and checksum(output / "report.json") == evidence["report_sha256"]):
        return evidence["timing"]
    return None
