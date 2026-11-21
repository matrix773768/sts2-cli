"""Replay and resample the single frozen Underworld witness."""
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
CASE = ("nosl3c-iid-release-independent", 0, "000025")


def risks(output, solver):
    targets = completion.targets
    targets.configure()
    versions = bind(output, solver)
    data = json.loads((HERE.parent / "m1-nosl3c-iig-completion/evidence.json").read_bytes())
    row, = [row for row in data["original_risks"]["results"]
            if (row["ledger"], row["step"], row["root"]) == CASE]
    with ExitStack() as stack:
        game = targets.open_worker(output, stack, versions)
        targets.CAPTURE(game, row["spec"])
        actual = game.request("i1_iif_direct", fixed_actions=row["route"])["boundaries"]
    assert len(actual) == len(row["boundaries"]) == 2
    assert all(not any("UNDERWORLD.OnPlay" in gap for gap in frame["gaps"]) for frame in actual)
    assert any(power["id"] == "UNDERWORLD_POWER" and power["amount"] == 1
               for power in actual[-1]["powers"])
    save_json(output / "risks.json", dict(engine=versions, before=row["boundaries"], after=actual))


if __name__ == "__main__":
    mode = sys.argv.pop(1)
    completion.bind = bind
    if mode == "prefix":
        runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/probe_prefix.py"),
                       run_name="__main__")
    elif mode in ("resample", "risks"):
        output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
        output.mkdir(parents=True)
        resample = tools["resample"]
        collect = FunctionType(resample.__code__, resample.__globals__ | {"CASES": (CASE,)})
        (collect if mode == "resample" else risks)(output, solver)
    else:
        raise ValueError(mode)
