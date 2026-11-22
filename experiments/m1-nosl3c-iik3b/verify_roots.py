"""Run single-root route replays and resample only fully matched prefixes."""
from pathlib import Path
import runpy
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import probe

CASES = (
    ("pair16", 0, "000014", 19),
    ("holdout", 0, "000014", 3),
    ("holdout", 0, "000027", 6),
    ("holdout", 1, "000013", 20),
)


def replay(output, solver):
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    for suite, step, root, length in CASES:
        batch = tools["batch"](f"iij5b-serial-{suite}", step, root)
        assert len(batch["rows"][0]["transitions"]) == length
        start = perf_counter()
        result = probe(output, versions, batch, False, False)
        seconds = perf_counter() - start
        tools["save_json"](output / f"{suite}-{step}-{root}.json",
                           dict(seconds=seconds, engine=versions, result=result))
        print(suite, step, root, result["status"], result.get("last_stable"),
              result.get("position"), seconds, flush=True)


def resample(output, solver, replays):
    import json
    sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iij2"))
    from resample import main

    for suite, step, root, length in CASES:
        result = json.loads((replays / f"{suite}-{step}-{root}.json").read_bytes())["result"]
        if result.get("last_stable") != length - 1 or result["status"] != "active":
            continue
        start = perf_counter()
        main(output / f"{suite}-{step}-{root}", solver, suite=suite,
             cases=((step, root),), ledger_name=f"iij5b-serial-{suite}")
        print(suite, step, root, perf_counter() - start, flush=True)


if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:3])
    if len(sys.argv) == 3:
        replay(output, solver)
    else:
        resample(output, solver, Path(sys.argv[3]).resolve())
