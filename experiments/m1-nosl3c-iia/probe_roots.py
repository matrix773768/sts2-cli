"""Verify native schema-3 roots and public equivalence under hidden permutations."""
from contextlib import ExitStack
from copy import deepcopy
import json

import torch

from qualify import BINDING, HOST, SPEC
from contract import Decision, Policy, public_observation
from nosl_model import WIDTH


def probe(output):
    BINDING["solver_binding"].__globals__["HOST"] = HOST
    versions = BINDING["solver_binding"](output, BINDING["FROZEN"], None)
    capture = BINDING["b1b"].synth.capture

    def open_game(stack):
        return BINDING["attested"](output, stack, versions)[0]

    with ExitStack() as stack:
        catalog = open_game(stack).request("synthetic_catalog")
    third = next(a for a in catalog["acts"] if a["act"] == 3)
    encounter = next(e["id"] for e in third["encounters"] if e["room"] == "Monster")
    roots = []
    for player in catalog["characters"]:
        role = player["name"]
        strike = f"STRIKE_{role.upper()}"
        spec = SPEC | dict(character=role, act=3, act_variant=third["variant"], encounter=encounter,
                           hp=player["max_hp"], max_hp=player["max_hp"],
                           deck=[dict(id=strike, upgrade=i % 2) for i in range(41)])
        with ExitStack() as stack:
            root, _ = capture(open_game(stack), spec)
        native = root["native"]
        assert (native["act"], native["act_variant"], native["deck"]) == (3, third["variant"], spec["deck"])
        roots.append(dict(spec=spec, native_constructed=True))

    spec = SPEC | dict(act_variant="UNDERDOCKS", encounter="CORPSE_SLUGS_WEAK",
                       deck=[dict(id=card, upgrade=0) for card in (
                           "INFLAME", "TWIN_STRIKE", "BASH", "SHRUG_IT_OFF", "STRIKE_IRONCLAD",
                           "DEFEND_IRONCLAD", "POMMEL_STRIKE", "IRON_WAVE", "HEADBUTT", "FLAME_BARRIER")])

    def inspect(root_spec):
        with ExitStack() as stack:
            game = open_game(stack)
            native, _ = capture(game, root_spec)
            state = game.request("i1_n2_reset", arm="A", cap=64, potions=False, rejected=[])["episode"]
            assert state["status"] == "active", state
            game.request("i1_n2_close")
            return native["native"]["draw"], public_observation(state["observation"])

    draw, obs = inspect(spec)
    alternate = deepcopy(spec)
    left, right = (c.split("+", 1)[0] for c in draw[:2])
    deck = alternate["deck"]
    i, j = (next(i for i, c in enumerate(deck) if c["id"] == card) for card in (left, right))
    deck[i], deck[j] = deck[j], deck[i]
    other_draw, other_obs = inspect(alternate)
    assert draw != other_draw and obs == other_obs
    torch.manual_seed(13)
    policy = Policy()
    history = torch.zeros(WIDTH)
    with torch.no_grad():
        first, second = [policy(Decision(o), history)[0].softmax(0) for o in (obs, other_obs)]
    assert torch.equal(first, second)
    return dict(versions=versions, roots=roots, hidden_order_differs=True,
                observations_equal=True, probabilities_equal=True, legal_actions=len(obs["actions"]))


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "roots.json").write_text(json.dumps(probe(output), indent=2), encoding="utf-8")
