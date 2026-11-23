"""Interrupt a real producer after durable writes and compare its recovered prefix."""
import argparse
from contextlib import closing
import ctypes as c
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from time import monotonic, sleep


def rows(dataset, recover=False):
    if not dataset.is_file():
        return {}
    uri = dataset.resolve().as_uri() + ("?mode=rw" if recover else "?mode=ro")
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as db:
            return dict(db.execute("SELECT ordinal, sha FROM trajectories"))
    except sqlite3.OperationalError as error:
        if str(error) not in ("database is locked", "no such table: trajectories"):
            raise
        return {}


def running_prefix(child, dataset, committed):
    deadline = monotonic() + 240
    while len(rows(dataset)) < committed:
        if child.poll() is not None or monotonic() >= deadline:
            raise RuntimeError("Producer exited or did not reach the interruption point")
        sleep(0.1)


def producer_command(output, host, count, recycle):
    return [sys.executable, "-X", "utf8", str(Path(__file__).with_name("run.py")),
            str(output), "--host", str(host), "--fast", "--workers", "4",
            "--recycle", str(recycle), "--count", str(count)]


def native_workers(parent):
    class Process(c.Structure):
        _fields_ = [
            ("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD),
            ("heap", c.c_size_t), ("module", wt.DWORD), ("threads", wt.DWORD),
            ("parent", wt.DWORD), ("priority", wt.LONG), ("flags", wt.DWORD),
            ("image", wt.WCHAR * 260),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wt.DWORD, wt.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
    for method in (kernel.Process32FirstW, kernel.Process32NextW):
        method.argtypes = (wt.HANDLE, c.POINTER(Process))
        method.restype = wt.BOOL
    kernel.CloseHandle.argtypes = (wt.HANDLE,)
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        process = Process(size=c.sizeof(Process))
        available = kernel.Process32FirstW(handle, c.byref(process))
        while available:
            if process.parent == parent and process.image.casefold() == "dotnet.exe":
                yield process.pid
            available = kernel.Process32NextW(handle, c.byref(process))
    finally:
        kernel.CloseHandle(handle)


def worker_fault(output, host):
    output.mkdir()
    dataset = output / "dataset.sqlite"
    with (output / "fault.log").open("wb") as log:
        child = subprocess.Popen(producer_command(output, host, 48, 32), stdout=log,
                                 stderr=subprocess.STDOUT)
        try:
            running_prefix(child, dataset, 8)
            pids = list(native_workers(child.pid))
            if not pids:
                raise RuntimeError("No native child worker is active")
            pid = pids[0]
            os.kill(pid, signal.SIGTERM)
            if child.wait(timeout=180) != 0:
                raise RuntimeError("Producer failed after one host was killed")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    report, = output.glob("run-*.json")
    result = json.loads(report.read_bytes())
    failed, = [event for event in result["worker_events"] if event["pid"] == pid]
    if failed["exit_code"] == 0 or result["process_count"] <= 4 or result["attempts"] != 48:
        raise ValueError("Host failure and replacement were not observed")
    return dict(killed_pid=pid, exit_code=failed["exit_code"], reason=failed["reason"],
                attempts=result["attempts"], complete=result["complete"],
                process_count=result["process_count"])


def probe(output, host, reference, committed, through):
    if not 0 < committed < through:
        raise ValueError("Expected an interrupted prefix smaller than the reference prefix")
    output.mkdir()
    dataset = output / "dataset.sqlite"
    with (output / "interrupted.log").open("wb") as log:
        child = subprocess.Popen(producer_command(output, host, through * 4, 16), stdout=log,
                                 stderr=subprocess.STDOUT)
        try:
            running_prefix(child, dataset, committed)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    before = rows(dataset, recover=True)
    with (output / "resumed.log").open("wb") as log:
        subprocess.run(producer_command(output, host, through, 16), stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=300)
    after = rows(dataset)
    expected = {i: sha for i, sha in rows(reference).items() if i < through}
    if len(expected) != through or after != expected or any(after.get(i) != sha for i, sha in before.items()):
        raise ValueError("Recovery changed a committed row or diverged from cold-independent evidence")
    result = dict(interrupted_exit_code=child.returncode, committed_before=len(before),
                  committed_after=len(after), newly_committed=len(after)-len(before),
                  exact_prefix_match=True)
    fault = output.with_name(output.name + "-worker-fault")
    result["worker_fault"] = worker_fault(fault, host)
    (output / "recovery.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--committed", type=int, default=64)
    parser.add_argument("--through", type=int, default=96)
    args = parser.parse_args()
    print(json.dumps(probe(args.output, args.host, args.reference, args.committed, args.through), indent=2))
