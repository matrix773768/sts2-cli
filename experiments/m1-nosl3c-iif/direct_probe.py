"""Replay completed interactive plans through the original Solver without search."""
from contextlib import ExitStack
from pathlib import Path
from types import FunctionType
import argparse
import os

from audit import targets
from compare_frozen import entries
from replay_frozen import replay
from nosl_experience import save_json


def plans(output, versions, spec, row):
    actions = []

    class Trace:
        def __init__(self, game):
            self.game = game

        def request(self, command, *args, **kwargs):
            pending = None
            if command == "i1_n2_step":
                pos = kwargs["position"]
                if row["transitions"][pos]["observation"]["decision"]["phase"] == "combat":
                    pending = self.game.request("i1_iif_current_plan", **kwargs)["plan"]
            result = self.game.request(command, *args, **kwargs)
            if command == "i1_n2_step":
                episode = result["episode"]
                action = episode.get("audit_action")
                if action is not None and episode.get("audit_stamp"):
                    actions.append(action)
                elif pending is not None and episode["status"] == "unsupported":
                    actions.append(pending)
            return result

        def __getattr__(self, key):
            return getattr(self.game, key)

    def worker(*args):
        return Trace(targets.open_worker(*args))

    run = FunctionType(replay.__code__, replay.__globals__ | dict(
        open_worker=worker, certify=lambda *_: {}))
    run(output, versions, spec, row)
    return actions


def run(output, solver, ledger):
    targets.configure()
    bind = FunctionType(targets.bind.__code__, targets.bind.__globals__ | {"HOST": "m1-nosl3c-iif-build"})
    versions = bind(output, solver)
    selected = [(f"{step}:{key}", b) for step, key, b in entries(ledger)
                if b["rows"] and (b["status"] == "unsupported"
                                  or key in ("000002", "000013", "000018"))]
    originals = []
    for key,b in selected:
        try:
            actions = plans(output, versions, b["spec"], b["rows"][0])
        except targets.BANK.f1.i2.StopRun:
            actions = []
        if actions:
            originals.append((key,b["spec"],actions))
    dll = targets.BANK.f1.i2.SOLVER
    from hashlib import sha256
    identity = versions | dict(solver="0.51.5", solver_sha256=sha256(dll.read_bytes()).hexdigest())
    os.environ["I1_SOLVER"] = str(dll)
    results = []
    for key,spec,actions in originals:
        try:
            with ExitStack() as stack:
                worker = targets.open_worker(output, stack, identity)
                targets.CAPTURE(worker, spec)
                result = worker.request("i1_iif_direct", fixed_actions=actions)
            results.append(dict(position=key, submitted=len(actions), boundaries=result["boundaries"]))
        except (targets.BANK.f1.i2.StopRun, KeyError, ValueError, RuntimeError) as error:
            results.append(dict(position=key, submitted=len(actions), error=str(error)[:300]))
    save_json(output/"solver-direct.json",dict(engine=identity, results=results))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("ledger",type=Path)
    parser.add_argument("--solver",type=Path,required=True)
    a=parser.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    run(a.output.resolve(),a.solver.resolve(),a.ledger)
