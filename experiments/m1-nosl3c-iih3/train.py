"""Run v4 with versioned enemy-side exact battle admission."""
import argparse
from pathlib import Path
from types import FunctionType

from certification import HERE, RULE, bind, certify
import train_completion as frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--suite", choices=("integration", "pair16", "holdout", "e3-update"), required=True)
    parser.add_argument("--through-update", type=int)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    frozen.torch.set_num_threads(1)
    frozen.torch.use_deterministic_algorithms(True)
    run = FunctionType(frozen.run.__code__, frozen.run.__globals__ |
                       dict(HERE=HERE, RULE=RULE, bind=bind, certify=certify))
    suite = "pair16" if args.suite == "e3-update" else args.suite
    config = frozen.configuration(suite, output)
    if args.workers is not None:
        config["workers"] = args.workers
    if args.suite == "e3-update":
        config["audit_only"] = False
        config["stages"][0]["updates"] = 2
    run(output, args.solver.resolve(), config, "exact", args.through_update)


if __name__ == "__main__":
    main()
