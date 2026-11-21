"""Bind the existing II-H.3 replay and training suites to the pinned II-H.9 pair."""
from pathlib import Path
import runpy
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih3"))
import certification

SOLVER = "509eece4ef6a2be9e098e2b78d27e25736964e5c4ae5f7aa0d557c8680d77181"
HEADLESS = "b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0"
original = certification.bind
host_bind = FunctionType(original.__code__, original.__globals__ |
                         {"HOST": "m1-nosl3c-iih7-host"})


def bind(output, solver):
    versions = host_bind(output, solver)
    if (versions["solver"], versions["solver_sha256"], versions["headless_sha256"],
        versions["coreclr"]) != ("0.51.5-iih.8.1", SOLVER, HEADLESS, "9.0.7"):
        raise ValueError("Unexpected II-H.9 build identity")
    return versions


if __name__ == "__main__":
    command = sys.argv.pop(1)
    if command not in ("replay", "train"):
        raise ValueError(command)
    certification.bind = bind
    certification.SOLVER = SOLVER
    runpy.run_path(str(HERE.parent / "m1-nosl3c-iih3" / (command + ".py")),
                   run_name="__main__")
