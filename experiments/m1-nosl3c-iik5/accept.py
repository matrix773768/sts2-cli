"""Bind II-J.5B acceptance to both DLLs in the cumulative II-K host."""
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
HOST = Path("logs/iik4b-host-final").resolve()
SOLVER_HASH = "b4db8cae5abada95a3a51caac31bbae9f356fb553949b3c7d4b14ea10d181c53"
HOST_HASH = "b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0"
GODOT_HASH = "82b8ecbc4fee2f6490a27aa1a509c48b646bf9f35e5bfad07699487a539ca9aa"
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iik4b"))
import verify_host
import certification
import replay

original = verify_host.binder(HOST)


def bind(output, solver):
    engine = original(output, solver)
    assert (engine["solver_sha256"], engine["headless_sha256"], engine["godot_sha256"],
            engine["coreclr"], engine["game"], engine["game_sha256"]) == (
                SOLVER_HASH, HOST_HASH, GODOT_HASH, "9.0.7", "0.113.1/26660232", certification.GAME)
    return engine | {"combat_host": "II-K.4B",
                     "native_identity": sha256((engine["native_identity"] + GODOT_HASH).encode()).hexdigest()}


def main():
    mode = sys.argv.pop(1)
    certification.bind = bind
    certification.SOLVER = SOLVER_HASH
    replay.bind = bind
    if mode in ("train", "replay"):
        runpy.run_path(str(certification.HERE / f"{mode}.py"), run_name="__main__")
    elif mode == "script":
        file = Path(sys.argv.pop(1)).resolve()
        sys.argv[0] = str(file)
        sys.path.insert(0, str(file.parent))
        runpy.run_path(str(file), run_name="__main__")
    elif mode == "seed":
        seed = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9b/seed_pair16.py"))["seed"]
        seed(*(Path(p) for p in sys.argv[1:]), solver_version="0.51.5-iik.3b")
    elif mode == "identity":
        output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
        output.mkdir(parents=True)
        print(json.dumps(bind(output, solver), indent=2))
    else:
        raise ValueError(mode)


if __name__ == "__main__":
    main()
