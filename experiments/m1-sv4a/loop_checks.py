"""Exercise actual public graph selection, private-world invariance, and replay."""
from pathlib import Path
import random
import json

from loop_common import ROOT, write_json
from loop_battle import collect
from loop_policy import BattlePolicy, NetworkPolicy


def recipe(cards, seed):
    return dict(schema=2, character="Ironclad", ascension=0, act=1, act_variant="OVERGROWTH",
        encounter="CUBEX_CONSTRUCT_NORMAL", seed=seed, hp=80, max_hp=80, relics=[], potions=[],
        deck=[dict(id=card, upgrade=0) for card in cards])


def run_checks(host, cfg, condition, output):
    if (output / "summary.json").exists():
        return json.loads((output / "summary.json").read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    model = NetworkPolicy(ROOT/cfg["g0"], condition, 350, 0., host.version, cfg)
    forward = lambda features: next(model.forward([(features,)]))
    lane = host.lane()
    try:
        deck = ["ARMAMENTS", "POMMEL_STRIKE", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"]
        job = [0, recipe(deck, "SV4APUBLIC"), "evaluation", "fixture", "Monster"]
        policy = BattlePolicy(model, host.project, forward, random.Random(7))
        result = collect(lane, policy, model.definition,
            dict(config=dict(action_cap=80, version="fixture"), purpose="fixture"), job, "terminal_fixture",
            {"enemy_hp": 4})
        if result["row"]["status"] != "predicted_win" or result["counts"].get("terminal_verified", 0) != 1:
            raise ValueError(f"Could not verify predicted terminal: {result['row']['status']}, {result['counts']}")
        deck = ["POMMEL_STRIKE"]*4 + ["STRIKE_IRONCLAD"]*2 + ["DEFEND_IRONCLAD", "BASH"]
        observations, worlds, actions, choices = [], [], [], []
        for seed in ("SV1HIDDEN05", "SV1HIDDEN13"):
            lane.open()
            ep = lane.request("pre0_start", cap=128, sv1_fixture={"enemy_hp":40}, spec=recipe(deck, seed))["episode"]
            obs = host.project(ep["observation"])
            observations.append(obs)
            private = lane.request("i1_iid_prediction_text")["text"]
            worlds.append(private.split(";D=",1)[1].split(";C=",1)[0])
            controller = BattlePolicy(model, host.project, forward, random.Random(1))
            actions.append(controller.act(obs, lane, 0))
            choices.append(controller.trace)
            lane.reset()
        if not observations[0] == observations[1] or worlds[0] == worlds[1]:
            raise ValueError("Hidden-order fixture did not produce equivalent public observations")
        if actions[0] != actions[1] or choices[0] != choices[1]:
            raise ValueError("Hidden draw order changed the fair search")
        report = dict(terminal_verified=result["counts"]["terminal_verified"], hidden_worlds_checked=2,
            equivalent_public_policies=True, first_index=actions[0][0],
            graph_boundaries=result["counts"]["boundaries"])
        write_json(output / "summary.json", report)
        print(report, flush=True)
        return report
    finally:
        host.close()
