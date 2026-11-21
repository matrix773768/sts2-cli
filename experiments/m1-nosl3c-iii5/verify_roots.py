"""Replay and resample the two Calcify witnesses."""
from contextlib import ExitStack
import json
from pathlib import Path
import runpy
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii1/verify_roots.py"))
bind = tools["bind"]
completion = tools["completion"]
from nosl_experience import save_json
CASES = (("nosl3c-iid-release-independent", 0, "000027"),
         ("nosl3c-iie-broad", 1, "000000"))


def risks(output, solver):
    targets = completion.targets
    targets.configure()
    versions = bind(output, solver)
    data = json.loads((HERE.parent / "m1-nosl3c-iig-completion/evidence.json").read_bytes())
    results = []
    for row in data["original_risks"]["results"]:
        if (row["ledger"], row["step"], row["root"]) not in CASES:
            continue
        with ExitStack() as stack:
            game = targets.open_worker(output, stack, versions)
            targets.CAPTURE(game, row["spec"])
            actual = game.request("i1_iif_direct", fixed_actions=row["route"])["boundaries"]
        assert len(actual) == len(row["boundaries"])
        assert all(not any("CALCIFY.OnPlay" in gap for gap in frame["gaps"]) for frame in actual)
        results.append(dict(ledger=row["ledger"], step=row["step"], root=row["root"],
                            before=row["boundaries"], after=actual))
    assert len(results) == len(CASES)
    save_json(output / "risks.json", dict(engine=versions, results=results))



if __name__ == "__main__":
    mode = sys.argv.pop(1)
    completion.bind = bind
    if mode == "prefix":
        runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/probe_prefix.py"),
                       run_name="__main__")
    elif mode in ("resample", "risks"):
        output, solver = (Path(arg).resolve() for arg in sys.argv[1:3])
        output.mkdir(parents=True)
        resample = tools["resample"]
        selected = tuple(case for case in CASES if case[2] in sys.argv[3:])
        if mode == "resample" and not selected:
            raise ValueError("Select a verified root by its six-digit position")
        collect = FunctionType(resample.__code__, resample.__globals__ | {"CASES": selected})
        (collect if mode == "resample" else risks)(output, solver)
    else:
        raise ValueError(mode)
