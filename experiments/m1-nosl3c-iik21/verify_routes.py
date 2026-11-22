"""Compare the archived E3 witnesses at their original first-difference boundary."""
from pathlib import Path
import runpy
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import probe

PRIMARY = (("pair16", 0, "000006", 15), ("holdout", 1, "000010", 15))
RELATED = (("holdout", 1, "000020", 17), ("holdout", 1, "000021", 20),
           ("holdout", 0, "000023", 9))

if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:3])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    for suite, step, root, position in RELATED if "--related" in sys.argv[3:] else PRIMARY:
        start = perf_counter()
        batch = tools["batch"](f"iij5b-serial-{suite}", step, root)
        batch["rows"][0]["transitions"] = batch["rows"][0]["transitions"][:position + 1]
        result = probe(output, versions, batch, False, False)
        duration = perf_counter() - start
        tools["save_json"](output / f"{suite}-{step}-{root}.json",
                           dict(engine=versions, result=result, seconds=duration))
        print(suite, step, root, duration, result["status"], result.get("position"),
              result.get("differences"), flush=True)
