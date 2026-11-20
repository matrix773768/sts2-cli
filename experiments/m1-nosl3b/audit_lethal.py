"""Frozen-policy probe at a controllable, preview-verified lethal decision."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import torch

from analyze import card_for, pressure_context
from nosl3b_protocol import HERE, roots
from nosl3b_episode import baseline
from nosl3b_store import restore, tensors
from nosl_experience import public_observation, save_json, terminal
from nosl_model import Decision, WIDTH


def choose_setup(obs):
    return next((a for a in obs["actions"] if card_for(obs, a) in ("BASH", "STRIKE_IRONCLAD")),
                obs["actions"][-1])


def advance(game, state, action):
    return game.request("i1_n2_step", index=action["index"], position=state["actions"])["episode"]


def reset(game):
    return game.request("i1_n2_reset", arm="A", cap=96, potions=True, rejected=[])["episode"]


def before_lethal(game):
    state, history = reset(game), []
    for _ in range(20):
        obs = public_observation(state["observation"])
        if pressure_context(obs)["known_combat_lethal"]:
            return state, obs, history
        action = choose_setup(obs)
        history.append((obs, action["index"]))
        state = advance(game, state, action)
    raise ValueError("Controlled fixture failed to reach a lethal decision")


def lethal_action(obs):
    enemy = obs["enemies"][0]
    return next(a for a in obs["actions"] if a["target"] == enemy["index"] and
                (a["preview"] or {}).get("damage_per_hit") is not None and
                a["preview"]["damage_per_hit"] * a["preview"]["hits"] >= enemy["hp"] + enemy["block"])


@torch.no_grad()
def score(models, obs, prefix):
    kill = lethal_action(obs)
    potion = next(a for a in obs["actions"] if a["kind"] == "use_potion")
    d = Decision(obs)
    results = {}
    for key, policy in models.items():
        history = torch.zeros(WIDTH)
        for earlier, action_index in prefix:
            _, _, state, actions = policy(Decision(earlier), history)
            history = policy.remember(history, state, actions[action_index])
        probs = policy(d, history)[0].softmax(0).tolist()
        p, k = probs[potion["index"]], probs[kill["index"]]
        results[key] = dict(potion_probability=p, kill_probability=k,
                            potion_rank=1 + sum(x > p for x in probs),
                            lethal_rank=1 + sum(x > k for x in probs))
    return results


def main(output, config):
    torch.set_num_threads(1)
    root = next(roots(config, "train"))
    root["spec"] |= dict(seed="NOSL3ACHECK", potions=["FLEX_POTION"], hp=75,
                         deck=[dict(id=card, upgrade=0) for card in ("INFLAME", "TWIN_STRIKE",
                               "BASH", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD")])
    state = tensors((output / "resume-latest.pt").read_bytes())
    models, _ = restore(state["models"], config, resume=False)
    env = baseline.Prediction(output)
    with ExitStack() as stack:
        game, _, private = env.open(stack, root)
        current, obs, prefix = before_lethal(game)
        results = score(models, obs, prefix)
        kill = lethal_action(obs)
        without = terminal(advance(game, current, kill), kill)
        game.request("i1_n2_close")
        current, repeated, second_prefix = before_lethal(game)
        assert (obs, prefix) == (repeated, second_prefix)
        potion = next(a for a in obs["actions"] if a["kind"] == "use_potion")
        after = advance(game, current, potion)
        boosted = public_observation(after["observation"])
        attack = lethal_action(boosted)
        with_potion = terminal(advance(game, after, attack), attack)
        game.request("i1_n2_close")
    assert without["status"] == with_potion["status"] == "predicted_win"
    save_json(output / "audit-only" / "lethal-fixture.json.gz",
              dict(root=private, observation=obs, prefix=prefix, boosted=boosted, probabilities=results,
                   without=without, with_potion=with_potion), compress=True)
    save_json(output / "lethal-summary.json", dict(prefix_actions=len(prefix), turn=obs["turn"],
              player_hp=obs["hp"], enemy=obs["enemies"][0], energy=obs["energy"],
              kill_card=card_for(obs, kill), before_preview=kill["preview"], after_preview=attack["preview"],
              same_terminal_hp=without["observation"]["hp"] == with_potion["observation"]["hp"],
              potion_ranks=results))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "formal.json")
    args = p.parse_args()
    main(args.output.resolve(), json.loads(args.config.read_bytes()))
