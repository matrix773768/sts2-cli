"""Replay and resample only the archived II-J.1 Quasar witness."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iij2"))
from resample import main
from verify_guards import TOOLS, targets
from probe_prefix import probe


if __name__ == "__main__":
    mode, dest, build = sys.argv[1:]
    output, solver = Path(dest).resolve(), Path(build).resolve()
    if mode == "sample":
        main(output, solver, suite="pair16", cases=((0, "000000"),), ledger_name="iij1-resample")
    else:
        output.mkdir(parents=True)
        targets.configure()
        versions = TOOLS["bind"](output, solver)
        saved = TOOLS["batch"]("iij1-resample", 0, "000000")
        result = probe(output, versions, saved, False, False)
        TOOLS["save_json"](output / "route.json", dict(engine=versions, result=result))
