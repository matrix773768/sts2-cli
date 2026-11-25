"""Detached attempt supervisor and checkpoint signaling helpers."""

import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from time import sleep, time
import traceback

from .common import ROOT, lease, path_at, read, write
from .windows import attach, drain, process_identity, process_tree
from .timing import HEARTBEAT_SECONDS, execution_clock


PAUSED = 75


def stop_requested():
    path = os.environ.get("INF1_STOP")
    return bool(path and Path(path).is_file())


def progress(done, target, checkpoint=None, **metrics):
    path = Path(os.environ["INF1_PROGRESS"])
    seconds = time()
    write(path, dict(done=done, target=target, checkpoint=str(checkpoint) if checkpoint else None,
                     timestamp=seconds, throughput=metrics.pop("throughput", None), **metrics))


def verify_progress(work, info):
    if not info or not 0 <= info["done"] <= info["target"]:
        raise ValueError("Adapter did not publish valid progress")
    if info["done"] and not info["checkpoint"]:
        raise ValueError("Committed work must identify a checkpoint")
    if info["checkpoint"]:
        file = path_at(work, info["checkpoint"])
        if not file.is_file() or file.suffix == ".partial":
            raise ValueError("Adapter checkpoint is missing or unfinished")
    return info


def supervise(work, token):
    # Reconciliation also takes this lease briefly. A busy lock does not invalidate a launch.
    while True:
        request = read(work / "request.json", {})
        if request.get("token") != token:
            return
        with lease(work / "attempt.lock") as acquired:
            if acquired:
                request = read(work / "request.json", {})
                attempt = work / "attempts" / token
                if request.get("token") == token and not (attempt / "owner.json").exists():
                    run_attempt(work, attempt, request)
                return
        sleep(.04)


def run_attempt(work, attempt, request):
    clock = execution_clock()
    started = time()
    owner = dict(token=request["token"], sha256=request["sha256"],
                 process=process_identity(os.getpid()), started=started)
    write(attempt / "owner.json", owner)
    result = dict(token=request["token"], started=started, exit_code=None, state="failed")
    with (attempt / "stdout.log").open("ab", buffering=0) as out, (attempt / "stderr.log").open("ab", buffering=0) as err:
        stop = Event()

        def pulse():
            write(attempt / "heartbeat.json", owner | {"observed": time(), "elapsed": execution_clock() - clock})

        def monitor():
            while not stop.wait(HEARTBEAT_SECONDS):
                try:
                    pulse()
                except OSError:
                    err.write(traceback.format_exc().encode())

        pulse()
        monitor_thread = Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            result.update(execute(work, attempt, request, owner, out, err, clock))
        except Exception as error:
            result["reason"] = str(error)
            err.write(traceback.format_exc().encode())
        finally:
            stop.set()
            monitor_thread.join()
    write(attempt / "result.json", result | {"ended": time(), "elapsed": execution_clock() - clock,
                                            "exit_confirmed": True})


def execute(work, attempt, request, owner, out, err, clock):
    env = os.environ | {"INF1_STOP": str(attempt / "stop.json"), "INF1_PROGRESS": str(work / "progress.json")}
    remaining = request["remaining"]
    deadline = clock + remaining if remaining is not None else None
    reason = None
    with process_tree() as job:
        # The gate cannot start the workload until its process tree belongs to the Job Object.
        gate = subprocess.Popen([sys.executable, "-m", "tools.training_manager.worker", "gate", str(attempt)],
                                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            attach(job, gate.pid)
            owner["gate"] = process_identity(gate.pid)
            write(attempt / "owner.json", owner)
            gate.stdin.write(b"1")
            gate.stdin.close()
            expired = False
            while gate.poll() is None:
                control = read(attempt / "stop.json", {})
                if control.get("reason") == "force":
                    reason = "force"
                    break
                if deadline is not None and execution_clock() >= deadline:
                    if not expired:
                        write(attempt / "budget.json", {"time": time()})
                        if not control:
                            write(attempt / "stop.json", {"reason": "budget"})
                        expired = True
                    reason = "budget"
                    if execution_clock() >= deadline + request["grace"]:
                        break
                sleep(.15)
        finally:
            if not gate.stdin.closed:
                gate.stdin.close()
            drain(job)
            gate.wait()
    code = gate.returncode
    if reason in ("force", "budget"):
        return dict(exit_code=code, state="cancelled", reason=reason)
    if code == 0:
        if request["resume"] == "checkpoint":
            info = verify_progress(work, read(work / "progress.json"))
            if info["done"] != info["target"]:
                raise ValueError("Adapter exited before its committed target")
        return dict(exit_code=code, state="completed")
    if code == PAUSED and (attempt / "stop.json").exists() and request["resume"] == "checkpoint":
        verify_progress(work, read(work / "progress.json"))
        return dict(exit_code=code, state="paused")
    return dict(exit_code=code, state="failed")


def gate(attempt):
    if sys.stdin.buffer.read(1) != b"1":
        return 1
    request = read(attempt / "launch.json")
    with subprocess.Popen(request["command"], cwd=request["cwd"], stdin=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW) as child:
        write(attempt / "child.json", process_identity(child.pid))
        return child.wait()


if __name__ == "__main__":
    if sys.argv[1] == "gate":
        raise SystemExit(gate(Path(sys.argv[2])))
    supervise(Path(sys.argv[1]), sys.argv[2])
