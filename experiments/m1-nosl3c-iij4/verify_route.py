"""Replay the fixed II-I.9A Hammer Time route."""
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
TOOLS = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import probe


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    TOOLS["targets"].configure()
    versions = TOOLS["bind"](output, solver)
    batch = TOOLS["batch"]("iii9a-sample-1", 0, "000000")
    result = probe(output, versions, batch, False, False)
    TOOLS["save_json"](output / "route.json", dict(engine=versions, result=result))
    print(result["status"], result.get("position"), result.get("differences"))
