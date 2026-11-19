"""Immutable policy input and an independent single-path episode client."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Card:
    index: int
    id: str
    upgrade: int


@dataclass(frozen=True, slots=True)
class Enemy:
    index: int
    hp: int
    block: int


@dataclass(frozen=True, slots=True)
class Action:
    index: int
    card: int | None = None
    target: int | None = None
    cost: int | None = None

    def native(self):
        if self.card is None:
            return {"action": "end_turn"}
        args = {"card_index": self.card}
        if self.target is not None:
            args["target_index"] = self.target
        return {"action": "play_card", "args": args}


@dataclass(frozen=True, slots=True)
class Observation:
    turn: int
    hp: int
    block: int
    energy: int
    draw_count: int
    hand: tuple[Card, ...]
    enemies: tuple[Enemy, ...]
    actions: tuple[Action, ...]

    @classmethod
    def decode(cls, wire):
        return cls(*(wire[field] for field in ("turn", "hp", "block", "energy", "draw_count")),
                   tuple(Card(**item) for item in wire["hand"]),
                   tuple(Enemy(**item) for item in wire["enemies"]),
                   tuple(Action(**item) for item in wire["actions"]))


class Episode:
    def __init__(self, worker):
        self.worker = worker
        self.state = None

    def reset(self):
        self.state = None
        reply = self.worker.request("i1_n2_reset", arm="A", cap=48, potions=False, rejected=[])
        self.state = reply.get("episode", reply)
        self.prepare_ms = reply.get("root_prepare_ms")
        return self.observation

    @property
    def observation(self):
        wire = self.state.get("observation")
        return Observation.decode(wire) if wire else None

    @property
    def done(self):
        return self.state["status"] != "active"

    def legal_actions(self):
        observation = self.observation
        return observation.actions if observation is not None else ()

    def result(self):
        if not self.done:
            raise ValueError("Episode is still active")
        return self.state

    def step(self, action):
        if self.done or action not in self.legal_actions():
            raise ValueError("Expected an action in the current active menu")
        self.state = self.worker.request("i1_n2_step", index=action.index,
                                         position=self.state["actions"])["episode"]
        return self.observation

    def close(self):
        self.worker.request("i1_n2_close")
        self.state = None


def choose(observation, actions, defense_first):
    def score(action):
        card = observation.hand[action.card]
        defense = card.id.startswith("DEFEND") or card.id in ("SHRUG_IT_OFF", "FLAME_BARRIER", "SURVIVOR")
        return (defense == defense_first, card.upgrade, -(action.target or 0))

    plays = [action for action in actions if action.card is not None]
    return max(plays, key=score) if plays else actions[-1]
