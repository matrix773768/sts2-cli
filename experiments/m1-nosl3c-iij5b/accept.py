"""Bind the existing acceptance runners to the II-J.4 build."""
from pathlib import Path
import runpy
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
PIN = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9a/replay.py"))
SOLVER = "2c7a9ec1d0f6a58226be9aee9230268b40ab96fa6efe582cddf2e376b9a18e5f"


def bind(output, solver):
    engine = PIN["bind_host"](output, solver)
    assert (engine["solver"], engine["solver_sha256"], engine["headless_sha256"],
            engine["coreclr"], engine["game_sha256"], engine["game"]) == (
                "0.51.5-iij.4", SOLVER, PIN["HOST"], "9.0.7",
                PIN["certification"].GAME, "0.113.1/26660232")
    return engine


if __name__ == "__main__":
    mode = sys.argv.pop(1)
    certification = PIN["certification"]
    certification.bind = bind
    certification.SOLVER = SOLVER
    if mode in ("train", "replay"):
        runpy.run_path(str(certification.HERE / f"{mode}.py"), run_name="__main__")
    elif mode == "risks":
        sys.path.insert(0, str(PIN["HERE"]))
        script = runpy.run_path(str(PIN["HERE"] / "risks.py"))
        main = script["main"]
        FunctionType(main.__code__, main.__globals__ | {"bind": bind})(
            *(Path(arg).resolve() for arg in sys.argv[1:]))
    elif mode == "seed":
        seed = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9b/seed_pair16.py"))["seed"]
        seed(*(Path(arg) for arg in sys.argv[1:]), solver_version="0.51.5-iij.4")
    elif mode == "identity":
        output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
        output.mkdir(parents=True)
        import json
        engine = bind(output, solver)
        print(json.dumps(engine, indent=2))
    else:
        raise ValueError(mode)
