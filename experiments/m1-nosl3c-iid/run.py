"""Run II-C admission with the opt-in target host."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

import torch

from targets import configure, run_admission

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--through-update", type=int)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    config["target_adapter"] = {
        source.name: sha256(source.read_bytes()).hexdigest()
        for source in sorted(Path(__file__).parent.glob("*.py"))
    }
    configure()
    run_admission.run(args.output.resolve(), args.solver.resolve(), config, args.workers,
                      args.through_update if args.through_update is not None else len(config.get("batches", [None])))
