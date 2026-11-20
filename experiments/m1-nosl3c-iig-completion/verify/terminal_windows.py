"""Capture native terminal windows for the four E3 witnesses without changing admission."""
import argparse
from pathlib import Path
import sys
from types import FunctionType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from completion_engine import bind, iig, targets
from compare_frozen import entries
from nosl_experience import save_json
from probe_prefix import native_step, probe
from replay_archive import read_matrix


def audit(output, versions, batch):
    live = None
    windows = []
    compare = iig.audit.compare_menu

    def observe(obs, current, slots):
        nonlocal live
        live = current
        compare(obs, current, slots)

    def step(native, action, slots, selected):
        if action["kind"] != "end_turn":
            return native_step(native, action, slots, selected)
        reply = native.request("i1_step", action={"kind": "EndTurn", "turn": live["round"]})
        if reply["type"] != "i1_state":
            raise ValueError(reply)
        if reply["terminal"]:
            attempted = native.request("action", action="end_turn", args={})
            repeated = native.request("i1_iib_native_stamp")
            windows.append(dict(before=reply["before_window"], locked=reply["terminal_window"],
                                native_decision=reply["decision"]["decision"],
                                locked_resources={key: reply["state"][0][key] for key in (
                                    "player_hp", "player_max_hp", "player_gold", "player_potions")},
                                repeat_decision=attempted.get("decision", attempted.get("type")),
                                locked_state_unchanged=repeated["terminal"]
                                and repeated["state"] == reply["state"]))
        return reply["decision"]

    try:
        iig.audit.compare_menu = observe
        run = FunctionType(probe.__code__, probe.__globals__ | {"native_step": step})
        result = run(output, versions, batch, False, False)
    finally:
        iig.audit.compare_menu = compare
    return dict(status=result["status"], initial_position=result.get("position"),
                fields=result.get("differences"), windows=windows)


def verify(output, solver, ledgers):
    targets.configure()
    versions = bind(output, solver)
    source = read_matrix()
    results = []
    for ledger in ledgers:
        chosen = {(r["step"], r["position"]) for r in source[ledger.name] if r["category"] == "rule_risk"}
        for step, root, batch in entries(ledger):
            if (step, root) in chosen:
                results.append(dict(ledger=ledger.name, step=step, root=root,
                                    **audit(output, versions, batch)))
                save_json(output / "terminal-windows.json", dict(engine=versions, results=results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", type=Path, nargs="+")
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verify(output, args.solver.resolve(), args.ledgers)
