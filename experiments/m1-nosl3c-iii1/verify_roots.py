"""Run the two stored Hammer Time roots under the pinned II-H.7 host."""
from pathlib import Path
from contextlib import ExitStack
import json
import runpy
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih7"))
from replay import bind, bind_iih3

completion = bind_iih3.__globals__["completion"]
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iig-completion"))
from compare_frozen import entries

CASES = (("nosl3c-iie-broad", 1, "000002"),
         ("nosl3c-iic-random-final", 0, "000003"))


def resample(output, solver):
    from train_completion import configuration, run, torch

    specs = [next(batch["spec"] for s, p, batch in entries(Path("logs") / ledger)
                  if (s, p) == (step, position))
             for ledger, step, position in CASES]
    config = configuration("pair16", output)
    del config["stages"]
    config.update(batches=[specs], workers=1, audit_only=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    run(output, solver, config, "exact", None)


def risks(output, solver):
    targets = completion.targets
    targets.configure()
    versions = bind(output, solver)
    source = json.loads((HERE.parent / "m1-nosl3c-iig-completion/evidence.json").read_bytes())
    cases = []
    for row in source["original_risks"]["results"]:
        if (row["ledger"], row["step"], row["root"]) not in CASES:
            continue
        with ExitStack() as stack:
            game = targets.open_worker(output, stack, versions)
            targets.CAPTURE(game, row["spec"])
            after = game.request("i1_iif_direct", fixed_actions=row["route"])["boundaries"]
        assert len(after) == len(row["boundaries"])
        assert all(not any("HAMMER_TIME.OnPlay" in gap for gap in r["gaps"]) for r in after)
        cases.append(dict(ledger=row["ledger"], step=row["step"], root=row["root"],
                          before=row["boundaries"], after=after))
    assert len(cases) == len(CASES)
    (output / "risks.json").write_text(
        json.dumps(dict(engine=versions, cases=cases), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    mode = sys.argv.pop(1)
    completion.bind = bind
    if mode == "prefix":
        runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/probe_prefix.py"),
                       run_name="__main__")
    elif mode in ("resample", "risks"):
        output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
        output.mkdir(parents=True)
        (resample if mode == "resample" else risks)(output, solver)
    else:
        raise ValueError(mode)
