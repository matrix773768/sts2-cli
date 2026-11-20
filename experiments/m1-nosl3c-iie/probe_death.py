"""Reproduce an exact solo death and exercise the refusal path."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

from terminal_contract import certify, death_verified, targets
from nosl_experience import save_json, terminal


def probe(output, solver):
    targets.configure()
    versions = targets.worker_bind(output, solver)
    spec = dict(schema=3, character="Ironclad", act=1, act_variant="OVERGROWTH",
                encounter="SHRINKER_BEETLE_WEAK", ascension=0, seed="IIEDEATH",
                hp=1, max_hp=80, relics=[], potions=[],
                deck=[dict(id="DEFEND_IRONCLAD", upgrade=0)] * 5)
    with ExitStack() as stack:
        game = targets.open_worker(output, stack, versions)
        targets.CAPTURE(game, spec)
        state = game.request("i1_n2_reset", arm="A", cap=16, potions=False, rejected=[])["episode"]
        steps = []
        while state["status"] == "active":
            obs = targets.project(state["observation"])
            action = next(a for a in obs["actions"] if a["kind"] == "end_turn")
            i = state["actions"]
            steps.append(dict(observation=obs, action=action, position=i))
            state = game.request("i1_n2_step", position=i, index=action["index"])["episode"]
        game.request("i1_n2_close")
    row = dict(transitions=steps, feedback=terminal(state, action))
    result = certify(output, versions, spec, row)
    save_json(output / "death.json", dict(spec=spec, evidence=result, feedback=row["feedback"]))
    if result["status"] != "admissible_death":
        raise ValueError(result["status"])
    negative = deepcopy(result)
    negative["reason"] = "terminal_not_locked"
    negative["native_after"]["player"]["block"] += 1
    assert not death_verified(negative, row["feedback"])
    altered = deepcopy(row)
    altered["transitions"][0]["observation"]["hp"] += 1
    different_route = certify(output, versions, spec, altered)
    assert not different_route["terminal_verified"]
    save_json(output / "negative.json", dict(resource_mismatch_rejected=True,
               corrupted_prefix_status=different_route["status"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    probe(args.output.resolve(), args.solver.resolve())
