"""Replay the frozen Glass Orb witness through decision 20."""
from pathlib import Path
import runpy
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import probe

LEDGER = "iij5b-serial-holdout"
STEP = 1
ROOT = "000021"


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    batch = tools["batch"](LEDGER, STEP, ROOT)
    batch["rows"][0]["transitions"] = batch["rows"][0]["transitions"][:21]
    start = perf_counter()
    result = probe(output, versions, batch, False, False)
    duration = perf_counter() - start
    tools["save_json"](output / "route.json", dict(engine=versions, result=result, seconds=duration))
    print(duration, result["status"], result.get("position"), result.get("differences"))
