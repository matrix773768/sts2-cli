"""Offline comparison of selected continuations with original Solver Replay."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import bind, targets
from compare_frozen import entries
from nosl_experience import save_json
from probe_prefix import probe
from replay_archive import selection


def plans(output, versions, batch):
    completed = []
    pending = None
    base_worker = targets.open_worker

    class Recorder:
        def __init__(self, game):
            object.__setattr__(self, "game", game)

        def __getattr__(self, name):
            return getattr(self.game, name)

        def __setattr__(self, name, value):
            setattr(self.game, name, value)

        def request(self, command, *args, **kwargs):
            nonlocal pending
            result = self.game.request(command, *args, **kwargs)
            if command == "i1_n2_step":
                state = result["episode"]
                if state.get("audit_action") and state.get("audit_stamp"):
                    action = state["audit_action"]
                    if state.get("automatic") and (action.get("choice") or {}).get("cards") == []:
                        pending = len(completed), action | {"choice": None}
                    completed.append(action)
                elif (state.get("interaction_trace") or {}).get("action"):
                    pending = len(completed), state["interaction_trace"]["action"]
            return result

    try:
        targets.open_worker = lambda *args: Recorder(base_worker(*args))
        audit = probe(output, versions, batch, True, False)
    finally:
        targets.open_worker = base_worker
    return completed, pending, audit


def original_replay(output, versions, spec, route):
    if not route:
        return []
    with ExitStack() as stack:
        game = targets.open_worker(output, stack, versions)
        targets.CAPTURE(game, spec)
        return game.request("i1_iif_direct", fixed_actions=route)["boundaries"]


def compare(output, solver, ledgers, selected):
    targets.configure()
    versions = bind(output, solver)
    rows = []
    for ledger in ledgers:
        for step, root, batch in entries(ledger):
            if (ledger.name, step, root) not in selected:
                continue
            complete, pending, audit = plans(output, versions, batch)
            rows.append(dict(ledger=ledger.name, step=step, root=root, complete=complete,
                             pending=pending, audit_status=audit["status"], spec=batch["spec"]))
    frozen = targets.BANK.f1.i2.SOLVER
    original = versions | dict(solver="0.51.5", solver_sha256=sha256(frozen.read_bytes()).hexdigest())
    os.environ["I1_SOLVER"] = str(frozen)
    for row in rows:
        before_submit = row.pop("pending")
        if before_submit:
            offset, action = before_submit
            line = [*row["complete"][:offset], action]
            row["unanswered_boundaries"] = original_replay(output, original, row["spec"], line)
        row["answered_boundaries"] = original_replay(output, original, row["spec"], row["complete"])
    save_json(output / "original.json", dict(engine=original, completion=versions, routes=rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path, nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    compare(output, args.solver.resolve(), args.ledgers, selection(args.case))
