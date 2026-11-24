"""Small, transactional workload for INF1 integration tests."""

import argparse
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.training_manager.common import read, write
from tools.training_manager.worker import PAUSED, progress, stop_requested


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("count", type=int)
    parser.add_argument("--delay", type=float, default=.1)
    parser.add_argument("--failure", choices=("once", "always"))
    parser.add_argument("--dependency", type=Path)
    args = parser.parse_args()
    if args.dependency and not args.dependency.exists():
        return 10
    failure = args.work / "failure.json"
    if args.failure == "always" or (args.failure == "once" and not failure.exists()):
        write(failure, True)
        return 11
    checkpoint = args.work / "units.json"
    committed = read(checkpoint, [])
    while len(committed) < args.count and not stop_requested():
        sleep(args.delay)
        committed.append(len(committed))
        write(checkpoint, committed)
        progress(len(committed), args.count, checkpoint)
    progress(len(committed), args.count, checkpoint if committed else None)
    return 0 if len(committed) == args.count else PAUSED


if __name__ == "__main__":
    raise SystemExit(main())
