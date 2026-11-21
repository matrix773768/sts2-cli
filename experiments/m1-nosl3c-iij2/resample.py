"""Resample exactly two holdout roots with their archived policy and seeds."""
from contextlib import closing
from functools import partial
from pathlib import Path
import sqlite3
import sys
from types import FunctionType

from verify_guards import TOOLS, targets
import certification
from train_completion import configuration, torch
from training import Policy, checkpoint_policy


def main(output, solver, suite="holdout", cases=((0, "000020"), (1, "000005")), ledger_name=None):
    output.mkdir(parents=True)
    targets.configure()
    versions = TOOLS["bind"](output, solver)
    targets.worker_bind = TOOLS["bind"]
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    runner = targets.run_admission
    certify = FunctionType(certification.certify.__code__, certification.certify.__globals__ |
                          {"SOLVER": versions["solver_sha256"]})
    entry = targets.train_interactive.collect.__wrapped__
    collect = torch.no_grad()(FunctionType(entry.__code__, entry.__globals__ |
                              dict(project=targets.project, Decision=targets.Decision)))
    attempt = FunctionType(runner.attempt.__code__, runner.attempt.__globals__ |
                           dict(collect=collect, certify=partial(certify, mode="exact")))
    cap = configuration(suite, output)["action_cap"]
    ledger_name = ledger_name or f"iii9b-{suite}"
    ledger = (Path("logs") / ledger_name / "training.sqlite").resolve()
    source = runner.Journal.__new__(runner.Journal)
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as source.db:
        for step, root in cases:
            archived = TOOLS["batch"](ledger_name, step, root)
            old, = archived["rows"]
            behavior = old["behavior"]
            saved, _ = source.load(step)
            policy = Policy().eval()
            policy.load_state_dict(saved["model"])
            model_hash = runner.digest(checkpoint_policy(policy))
            assert model_hash == saved["model_sha256"] == behavior["model_sha256"]
            result = attempt(output, versions, archived["spec"], policy, model_hash, behavior["seed"], cap)
            common = 0
            new_rows = result["rows"]
            if new_rows:
                for before, after in zip(old["transitions"], new_rows[0]["transitions"]):
                    if before != after:
                        break
                    common += 1
            TOOLS["save_json"](output / f"{step}-{root}.json",
                               result | dict(root=f"{step}:{root}", behavior=behavior,
                                             common_prefix=common, cap=cap, engine=versions))


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
