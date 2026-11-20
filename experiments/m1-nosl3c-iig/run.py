"""Run the frozen v4 training engine with isolated IIG certification."""
import argparse
import json
from pathlib import Path
import runpy
from types import FunctionType

import torch

from bridge import HERE, VERSION, bind, certify, targets

BASE = runpy.run_path(str(HERE.parent/"m1-nosl3c-iif/train.py"))


def run(output,solver,config,mode,through):
    targets.worker_bind = bind
    old = BASE["run"]
    isolated = FunctionType(old.__code__,old.__globals__ | dict(HERE=HERE,VERSION=VERSION,certify=certify))
    isolated(output,solver,config,mode,through)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--solver",type=Path,required=True)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--mode",choices=("exact","semantic","diagnostic"),default="exact")
    parser.add_argument("--through-update",type=int)
    a=parser.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    run(a.output.resolve(),a.solver.resolve(),json.loads(a.config.read_bytes()),a.mode,a.through_update)
