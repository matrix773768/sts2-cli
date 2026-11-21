"""Replay historical inputs with the H.3 audit and the original route binder."""
import argparse
from pathlib import Path
from types import FunctionType

from certification import bind, certify
import replay_archive as frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", nargs=3, type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    compare = FunctionType(frozen.compare.__code__, frozen.compare.__globals__ | {"certify": certify})
    run = FunctionType(frozen.run.__code__, frozen.run.__globals__ | {"bind": bind, "compare": compare})
    run(args.output.resolve(), args.solver.resolve(), args.ledgers, args.workers, frozen.selection(args.case), False)


if __name__ == "__main__":
    main()
