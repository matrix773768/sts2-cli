"""Check equivalent public history through a genuinely revealed selector."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import torch

from engine import BANK, CAPTURE, bind, open_worker
from interactive_contract import Decision, Policy, WIDTH, project


@torch.no_grad()
def probe(output, solver):
    versions = bind(output, solver)
    base = json.loads((Path(__file__).parent / "integration.json").read_bytes())["batches"][0][0]
    base["deck"] = [dict(id="ACROBATICS", upgrade=0)] * 2 + [
                    dict(id="STRIKE_SILENT", upgrade=0)] * 6
    torch.manual_seed(11)
    policy = Policy().eval()
    seen = {}
    for index in range(24):
        spec = base | dict(seed=f"IIBEQUIV{index}")
        with ExitStack() as stack:
            game = open_worker(output, stack, versions)
            root, _ = CAPTURE(game, spec)
            source = game.request("f1_audit")
            state = game.request("i1_n2_reset", arm="A", cap=32, potions=False, rejected=[])["episode"]
            obs = project(state["observation"])
            history = torch.zeros(WIDTH)
            initial = Decision(obs)
            action = next((a for a in initial.actions if a["card"] is not None
                           and obs["hand"][a["card"]]["id"] == "ACROBATICS"), None)
            if action is None:
                continue
            logits, _, embedding, actions = policy(initial, history)
            history = policy.remember(history, embedding, actions[action["index"]])
            reply = game.request("i1_n2_step", position=0, index=action["index"])["episode"]
            after = project(reply["observation"])
            assert after["decision"]["phase"] == "choice"
            assert after["draw_count"] < obs["draw_count"]
            probabilities = [logits.softmax(0).tolist(), policy(Decision(after), history)[0].softmax(0).tolist()]
            private_rng = root["native"]["run_rng"]
            history_key = json.dumps([obs, action, after], sort_keys=True)
            game.request("i1_n2_close")
            assert game.request("f1_audit") == source
            if history_key in seen:
                old_seed, old_rng, old_probabilities = seen[history_key]
                if private_rng != old_rng:
                    assert probabilities == old_probabilities
                    return dict(versions=versions, seeds=[old_seed, spec["seed"]], rng_differs=True,
                                same_public_history=True, same_probabilities=True,
                                candidates=len(after["decision"]["candidates"]), pending_close_preserved_source=True)
            seen[history_key] = (spec["seed"], private_rng, probabilities)
    raise ValueError("No matched public histories")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    BANK.atomic(output / "equivalence.json", probe(output, args.solver))
