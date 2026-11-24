"""Operate the local INF1 queue from a Windows terminal."""

import argparse
import json
from pathlib import Path
import sys
from time import monotonic, sleep

from .common import HOME, MODES, ROOT, freeze, home_path, read, settings, write
from .manager import Manager
from .windows import detach, process_identity, resources


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--home", default=".", help="Queue subdirectory under logs/inf1")
    commands = cli.add_subparsers(dest="operation", required=True)
    commands.add_parser("list")
    commands.add_parser("resources")
    commands.add_parser("shutdown")
    commands.add_parser("stop-all")
    commands.add_parser("enable")
    start = commands.add_parser("start")
    start.add_argument("--foreground", action="store_true")
    start.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    mode = commands.add_parser("mode")
    mode.add_argument("mode", choices=MODES, nargs="?")
    validate = commands.add_parser("freeze")
    validate.add_argument("template", type=Path)
    validate.add_argument("destination", type=Path)
    commands.add_parser("submit").add_argument("spec", type=Path)
    commands.add_parser("status").add_argument("id", nargs="?")
    for name in ("pause", "resume", "cancel", "retry", "report"):
        sub = commands.add_parser(name)
        sub.add_argument("id")
        if name == "cancel":
            sub.add_argument("--force", action="store_true")
    args = cli.parse_args()
    home = home_path(args.home)
    op = args.operation
    if op == "freeze":
        destination = args.destination.resolve()
        if not destination.is_relative_to(home) or destination.exists():
            raise ValueError("Freeze to a new file under the INF1 queue directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        spec = freeze(read(args.template), home)
        write(destination, spec)
        print(spec["sha256"])
        return
    manager = Manager(home)
    if op == "start":
        if args.foreground or args.once:
            manager.run(once=args.once)
        else:
            owner = read(home / "manager.json")
            if owner and process_identity(owner["pid"]) == owner:
                raise ValueError(f"INF1 manager already running (PID {owner['pid']})")
            command = [sys.executable, "-m", "tools.training_manager", "--home",
                       str(home.relative_to(HOME)), "start", "--foreground"]
            with (home / "manager.log").open("ab") as log:
                process = detach(command, ROOT, log)
            deadline = monotonic() + 8
            while monotonic() < deadline:
                owner = read(home / "manager.json")
                if owner and owner["pid"] == process.pid and process_identity(process.pid) == owner:
                    break
                if process.poll() is not None:
                    raise ValueError(f"Manager exited at startup. See {home / 'manager.log'}")
                sleep(.05)
            else:
                raise ValueError(f"Manager did not acknowledge startup. See {home / 'manager.log'}")
            print(f"Started manager PID {process.pid}. Log: {home / 'manager.log'}")
    elif op == "submit":
        spec = read(args.spec)
        manager.submit(spec)
        print(spec["id"])
    elif op in ("status", "report") and args.id:
        dump(manager.report(manager.job(args.id)))
    elif op in ("list", "status"):
        cfg = settings(home)
        owner = read(home / "manager.json")
        if owner and process_identity(owner["pid"]) != owner:
            owner = None
        tasks = []
        for row in manager.rows():
            _, _, stage, work = manager.inspect(row)
            tasks.append(dict(id=row["id"], state=row["state"], stage=stage["id"] if stage else None,
                              reason=row["reason"], progress=read(work / "progress.json") if work else None))
        dump(dict(manager=owner, mode=manager.get_control("mode", cfg["mode"]),
                  enabled=manager.get_control("enabled", cfg["enabled"]),
                  resources=manager.get_control("resources"), tasks=tasks))
    elif op == "resources":
        dump(resources(home, gpu=True))
    elif op == "mode":
        if args.mode is not None:
            manager.control("mode", args.mode)
        print(manager.get_control("mode", settings(home)["mode"]))
    elif op in ("stop-all", "shutdown"):
        manager.stop(shutdown=op == "shutdown")
        print(op)
    elif op == "enable":
        manager.control("enabled", True)
        print(op)
    else:
        manager.request(args.id, "force" if getattr(args, "force", False) else op)
        print(manager.job(args.id)["state"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"INF1: {error}", file=sys.stderr)
        raise SystemExit(2) from None
