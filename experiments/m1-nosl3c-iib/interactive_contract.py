"""Allowlist and encode current v3 player decisions."""
from pathlib import Path
import sys

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iia"))
from contract import Decision as DecisionV2, Policy as PolicyV2, OBSERVATION as V2
from nosl_experience import ACTION_FIELDS, CARD_FIELDS, only
from nosl_model import WIDTH, mlp, token

OBSERVATION = "sts2.nosl_observation.v3"
MODEL = "nosl3c.interactive-actor-critic.v3"
TRANSITION = "sts2.nosl_transition.v3"


def project(wire):
    from contract import public_observation
    if wire["schema"] != OBSERVATION:
        raise ValueError("Wrong interactive wire version")
    phase = wire["decision"]["phase"]
    if phase not in ("combat", "choice"):
        raise ValueError("Unknown interactive decision phase")
    normalized = wire | {"schema": V2}
    if phase == "choice":
        normalized["actions"] = [dict(index=0, kind="end_turn", energy_x=False, star_x=False)]
    obs = public_observation(normalized)
    obs["schema"] = OBSERVATION
    obs["decision"] = {"phase": phase}
    if phase == "combat":
        if any(a["kind"] not in {"play_card", "end_turn"} for a in obs["actions"]):
            raise ValueError("Unavailable combat action")
        return obs

    raw = wire["decision"]
    decision = obs["decision"] = only(raw, ("phase", "effect", "pile", "timing", "min", "max", "selected"))
    decision["candidates"] = [only(c, CARD_FIELDS) for c in raw["candidates"]]
    candidates = list(range(len(decision["candidates"])))
    selected = decision["selected"]
    if ([c["index"] for c in decision["candidates"]] != candidates
            or not 0 <= decision["min"] <= min(decision["max"], len(candidates))
            or len(selected) != len(set(selected)) or set(selected) - set(candidates)
            or len(selected) > decision["max"]):
        raise ValueError("Invalid public choice shape")
    expected = [("select_candidate", i) for i in candidates if i not in selected
                and len(selected) < decision["max"]]
    if len(selected) >= decision["min"]:
        expected.append(("confirm_selection", None))
    actions = wire["actions"]
    if ([a["index"] for a in actions] != list(range(len(expected)))
            or [(a["kind"], a.get("choice")) for a in actions] != expected):
        raise ValueError("Incomplete choice menu")
    obs["actions"] = [only(a, ACTION_FIELDS) | dict(choice_zone=None, star_cost=None, energy_x=False,
                                                    star_x=False) for a in actions]
    return obs


class Decision(DecisionV2):
    def __init__(self, obs):
        if obs["schema"] != OBSERVATION:
            raise ValueError("Expected v3 observation")
        decision = obs["decision"]
        choice = decision["phase"] == "choice"
        candidates = decision.get("candidates", [])
        normalized = obs | {"schema": V2, "exhaust": [*obs["exhaust"], *candidates]}
        if choice:
            normalized["actions"] = [
                a | {"choice": None, "kind": "end_turn" if a["choice"] is None else "play_with_discard"}
                for a in obs["actions"]
            ]
        super().__init__(normalized)
        self.groups = [*self.groups[:3], obs["exhaust"], candidates]
        self.actions = obs["actions"]
        if choice:
            start = len(self.cards) - len(candidates) + 1
            context = token("|".join(decision[k] for k in ("effect", "pile", "timing")))
            for index, action in enumerate(self.actions):
                candidate = action["choice"]
                if candidate is not None:
                    self.refs[index, 1] = start + candidate
                self.pots[index] = context
                self.action_resources[index, -1] = 2 if candidate is None else 3


class Policy(PolicyV2):
    def __init__(self, mechanics=True, relations=True):
        super().__init__(mechanics, relations)
        self.state = mlp(7 * WIDTH + 13 + 16)
