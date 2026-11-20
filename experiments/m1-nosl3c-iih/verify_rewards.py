"""Replay frozen enemy-side wins and compare independently generated native rewards."""
import argparse
from pathlib import Path
import sys
from types import FunctionType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m1-nosl3c-iig-completion"))
from completion_engine import targets
from build_reward_host import HOST
from compare_frozen import entries
from nosl_experience import save_json
from probe_prefix import native_step, probe
from replay_archive import read_matrix


def audit(output, versions, batch):
    rewards = []
    turns = []

    def powers(native):
        stamp = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
        return next(field[2:] for field in stamp.split(";") if field.startswith("P="))

    def snapshot(native):
        state = native.request("i1_iih_reward_snapshot")
        return {key: state[key] for key in ("player", "run_rng", "player_rng", "room", "visited_map_nodes")}

    def step(native, action, slots, selected):
        before = snapshot(native) if action["kind"] == "end_turn" else None
        before_powers = powers(native) if before is not None else None
        decision = native_step(native, action, slots, selected)
        if before_powers is not None and decision and decision["decision"] in ("combat_play", "card_reward"):
            turns.append(dict(decision=decision["decision"], before=before_powers, after=powers(native)))
        if decision and decision["decision"] == "card_reward":
            offered = snapshot(native)
            repeat = native.request("action", action="end_turn", args={})
            if repeat != decision or snapshot(native) != offered:
                raise RuntimeError("Native reward offer changed after combat ended")
            claim = native.request("action", action="select_card_reward", args={"card_index": 0})
            claimed = snapshot(native)
            expected = decision["cards"][0]["id"]
            if (claimed["player"]["deck_size"] != offered["player"]["deck_size"] + 1
                    or claimed["player"]["deck"][-1]["id"] != expected):
                raise RuntimeError("Selected native reward did not enter the deck")
            rewards.append(dict(before=before, offer=decision, offered=offered, claim=claim, claimed=claimed))
        return decision

    replay = FunctionType(probe.__code__, probe.__globals__ | {"native_step": step})
    result = replay(output, versions, batch, False, False)
    if len(rewards) != 1:
        raise RuntimeError(f"No unique native reward window: {result['status']}")
    return dict(replay=result, native_turn_powers=turns, **rewards[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", nargs=3, type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets.configure()
    bind = targets.bind
    bound = FunctionType(bind.__code__, bind.__globals__ | {"HOST": HOST})
    versions = bound(output, args.solver.resolve())
    frozen = read_matrix()
    results = []
    for ledger in args.ledgers:
        cases = {(r["step"], r["position"]) for r in frozen[ledger.name] if r["category"] == "rule_risk"}
        for step, root, batch in entries(ledger):
            if (step, root) not in cases:
                continue
            left, right = (audit(output, versions, batch) for _ in range(2))
            equal = all(left[key] == right[key] for key in ("before", "offer", "offered", "claim", "claimed"))
            results.append(dict(ledger=ledger.name, step=step, root=root, native=left,
                                repeated=right, native_reward_equal=equal))
            save_json(output / "rewards.json", dict(engine=versions, results=results))


if __name__ == "__main__":
    main()
