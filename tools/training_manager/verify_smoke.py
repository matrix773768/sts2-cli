"""Exercise the submitted STS2 smoke plan on this Windows machine."""

import argparse
import subprocess
import sys
from time import monotonic, sleep, time

from .common import HOME, ROOT, home_path, read, write
from .manager import Manager
from .windows import process_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=".", help="Queue subdirectory under logs/inf1")
    parser.add_argument("--foreground", action="store_true",
                        help="Keep the test manager attached when OS sandboxing blocks detachment")
    parser.add_argument("--continue-experience", action="store_true",
                        help="Continue a previously observed and paused experience stage")
    args = parser.parse_args()
    home = home_path(args.home)
    manager = Manager(home)
    key = "sts2-smoke"
    expected = "paused" if args.continue_experience else "queued"
    if manager.job(key)["state"] != expected or manager.job(key)["stage"] != 0:
        raise ValueError(f"Expected the experience stage to be {expected}")
    events = read(home / "smoke-observed.json") if args.continue_experience else []

    def record(event, **values):
        entry = dict(event=event, timestamp=time(), **values)
        events.append(entry)
        write(home / "smoke-observed.json", events)
        print(entry, flush=True)

    def wait_for(check, timeout=120):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            row = manager.job(key)
            if row["state"] in ("failed", "cancelled", "interrupted"):
                raise RuntimeError(dict(row))
            value = check(row)
            if value:
                return value
            sleep(.04)
        raise TimeoutError(dict(manager.job(key)))

    def cli(*values):
        return [sys.executable, "-X", "utf8", "-m", "tools.training_manager", "--home", args.home, *values]

    def start():
        manager.control("enabled", True)
        if args.foreground:
            with (home / "acceptance-manager.log").open("ab") as stream:
                process = subprocess.Popen(cli("start", "--foreground"), cwd=ROOT,
                                           stdout=stream, stderr=stream)
            record("foreground launcher", manager_pid=process.pid)
        else:
            # Pass the escaped home through the environment instead of interpolating shell arguments.
            import os
            terminal = subprocess.Popen(["powershell.exe", "-NoProfile", "-Command",
                                         "python.exe -X utf8 -m tools.training_manager --home $env:INF1_SMOKE_HOME start"],
                                        cwd=ROOT, env=os.environ | {"INF1_SMOKE_HOME": str(home.relative_to(HOME))})
            if terminal.wait(timeout=15):
                raise RuntimeError("Detached launch failed")
            record("launch terminal exited", launcher_pid=terminal.pid)
        owner = wait_for(lambda _: live())
        record("manager live after launch", owner=owner)
        return owner

    def live():
        owner = read(home / "manager.json")
        return owner if owner and process_identity(owner["pid"]) == owner else None

    def stop():
        subprocess.run(cli("shutdown"), cwd=ROOT, check=True)
        deadline = monotonic() + 60
        while live() and monotonic() < deadline:
            sleep(.1)
        if live():
            raise TimeoutError("Manager failed to shut down")
        record("manager exited")

    def partial(stage, minimum):
        def check(row):
            spec, output, _, _ = manager.inspect(row)
            target = [item["id"] for item in spec["stages"]].index(stage)
            if row["stage"] > target:
                raise RuntimeError(f"Missed {stage} pause window")
            if row["stage"] < target:
                return None
            info = read(output / stage / "progress.json", {})
            return info if row["state"] == "running" and info.get("done", 0) >= minimum else None
        return wait_for(check)

    try:
        first = start()
        if not args.continue_experience:
            record("experience made progress", progress=partial("experience", 8))
            manager.request(key, "pause")
            wait_for(lambda row: row["state"] == "paused")
            record("experience paused", progress=manager.report(manager.job(key))["progress"])
            stop()
            second = start()
            if first == second:
                raise RuntimeError("Manager did not restart with a new process identity")
            manager.request(key, "resume")
        record("training made progress", progress=partial("training", 1))
        manager.request(key, "pause")
        wait_for(lambda row: row["state"] == "paused")
        record("GPU training paused", progress=manager.report(manager.job(key))["progress"])
        manager.request(key, "resume")
        wait_for(lambda row: row["state"] == "completed", timeout=240)
        report = manager.report(manager.job(key))
        finished = [run["stage"] for run in report["runs"] if run["outcome"]["state"] == "completed"]
        paused = {run["stage"] for run in report["runs"] if run["outcome"]["state"] == "paused"}
        if finished != ["experience", "features", "training", "development"] or not {"experience", "training"} <= paused:
            raise ValueError("Unexpected stage execution or replay")
        record("completed", stages=report["stages"], seconds=report["seconds"])
    finally:
        if live():
            stop()


if __name__ == "__main__":
    main()
