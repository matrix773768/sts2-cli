"""Run the II-I.9A frozen audit with the unchanged II-H.3 contract."""
from pathlib import Path
import runpy
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih3"))
import certification

SOLVER = "2a55d3dbdf89714366e192e4cf2ec4a4add17d89673831cd7fee9632501764ef"
HOST = "b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0"
original = certification.bind
bind_host = FunctionType(original.__code__, original.__globals__ |
                         {"HOST": "m1-nosl3c-iih7-host"})


def bind(output, solver):
    engine = bind_host(output, solver)
    if (engine["solver"], engine["solver_sha256"], engine["headless_sha256"],
            engine["coreclr"], engine["game_sha256"]) != (
            "0.51.5-iii.8", SOLVER, HOST, "9.0.7", certification.GAME):
        raise ValueError("Unexpected II-I.9A engine identity")
    return engine


if __name__ == "__main__":
    certification.bind = bind
    certification.SOLVER = SOLVER
    runpy.run_path(str(HERE.parent / "m1-nosl3c-iih3/replay.py"), run_name="__main__")
