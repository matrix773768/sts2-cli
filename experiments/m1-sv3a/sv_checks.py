"""Check the loaded value contract, live menus and predicted graph integration."""
import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path

import numpy as np
import torch

from sv_boundary import BoundaryScorer, contexts, fallback_action
from sv_data import ROOT, checksum, config, write_json
from sv_runtime import score_public, tensors
from sv_train import sample_rows
from evaluate import Actor, bind
from features import SOURCE_HASHES


def recipe(deck):
    return dict(schema=2, character="Ironclad", ascension=0, act=1, act_variant="OVERGROWTH",
        encounter="CUBEX_CONSTRUCT_NORMAL", seed="SV3ABOUNDARY", hp=80, max_hp=80, relics=[], potions=[],
        deck=[dict(id=card, upgrade=0) for card in deck])


def branch_check(output, build, checkpoint):
    os.chdir(ROOT)
    torch.set_num_threads(1)
    output.mkdir(parents=True, exist_ok=False)
    cfg = config()
    runtime, _ = bind(output, Path(cfg["host"]))
    engine = runtime["BANK"].f1.i2.engine_client
    binary = build / "host/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    solver = build / "solver-bin/CombatSolver.dll"
    identity = json.loads((build / "build.json").read_bytes())
    if checksum(solver) != identity["artifacts"]["solver-bin/CombatSolver.dll"]:
        raise ValueError("Instrumented Solver changed")
    command = engine.headless_command()
    engine.headless_command = lambda: [*command[:-1], str(binary)]
    os.environ.update(I1_SOLVER=str(solver), I1_LOG=".")
    project = runtime["targets"].project
    key = f"nosl3c.hp-loss-actor-critic.v4|{SOURCE_HASHES[1]}|sample"
    scorer = BoundaryScorer(checkpoint, key)
    encoder = scorer.encoder
    settings = dict(mode="k0", transitions=300, wall_ms=4000, depth=40,
                    memory_bytes=512*2**20, export_value=True)
    with closing(engine.EngineClient(log_root=output / "engine")) as game:
        opened = game.send(dict(cmd="pre0_start", cap=128, sv1_fixture={"enemy_hp": 4},
            spec=recipe(["ARMAMENTS", "POMMEL_STRIKE", "STRIKE_IRONCLAD",
                         "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"])))["episode"]
        observation = project(opened["observation"])
        initial = encoder.initial_history()
        actor = Actor(Path(cfg["pre1"]))
        actor.costs.measure = []
        fallback = fallback_action(actor, observation, initial)
        assert fallback in observation["actions"]
        features = encoder.encode(observation, initial) | dict(policy=scorer.policy, chosen=0)
        batch = tensors([features], "cpu")
        with torch.inference_mode():
            v, q = scorer.model(batch)
            v_selected, q_selected = scorer.model(batch, chosen_only=True)
            torch.testing.assert_close(v, v_selected)
            torch.testing.assert_close(q[:,0], q_selected)
            q_prob = scorer.model.probabilities(q)
            torch.testing.assert_close(q_prob.sum(-1), torch.ones_like(q_prob[..., 0]))
            modified = dict(batch, hidden_seed=torch.ones(1), label=torch.zeros(1), final_hp=torch.ones(1))
            torch.testing.assert_close(scorer.model(modified)[1], q)
        graph = game.send(dict(cmd="i1_sv1_graph", **settings))
        if graph.get("type") != "sv1_graph":
            raise RuntimeError(graph.get("message"))
        contexts_found = list(contexts(graph, project, encoder, initial))
        values = scorer.evaluate(contexts_found, batch_size=8)
        sources = Counter(item["source"] for item in values.values())
        assert sources["terminal"] > 0 and sources["q"] > 0
        scored = {item["kind"] for item in values.values() if item["source"] == "q"}
        assert {"end_play_a", "random"} <= scored
        try:
            list(contexts(graph | {"oracle": True}, project, encoder, initial))
            raise AssertionError("Oracle graph was admitted")
        except ValueError as error:
            assert "Oracle" in str(error)
        armaments = next(a for a in observation["actions"] if a["kind"] == "play_card"
                        and observation["hand"][a["card"]]["id"] == "ARMAMENTS")
        next_view = game.send(dict(cmd="i1_n2_step", position=0, index=armaments["index"]))["episode"]
        choice = project(next_view["observation"])
        assert choice["decision"]["phase"] == "choice"
        memory = encoder.update(initial, observation, armaments)
        data = tensors([encoder.encode(choice, memory) | {"policy": scorer.policy}], "cpu")
        with torch.inference_mode():
            _, pending = scorer.model(data)
            assert pending.shape[1] == len(choice["actions"])
        mixed = score_public(scorer.model, encoder, [(observation, initial, scorer.policy),
                                                     (choice, memory, scorer.policy)])
        assert [[item["action"] for item in result["q"]] for result in mixed] == [
            observation["actions"], choice["actions"]]
        rows, weights = sample_rows({"trajectory": np.array([0,0,1,2,2,2,2])}, 2,
                                    np.random.default_rng(0))
        assert len(rows) == 5 and np.isclose(weights[rows].sum(), 3)
        result = dict(source_counts=sources, exported_stable_nodes=len(graph["graph"]["public_decisions"]),
                      a_and_random=sorted(scored), choice_actions=len(choice["actions"]), fallback=fallback["kind"],
                      oracle_rejected=True, all_actions_equal_to_chosen=True, hidden_fields_ignored=True)
        write_json(output / "summary.json", result)
        print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("build", type=Path)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    branch_check(args.output.resolve(), args.build.resolve(), args.checkpoint.resolve())
