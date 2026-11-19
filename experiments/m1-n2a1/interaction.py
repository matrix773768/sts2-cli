"""N2A.1 observation decoding and feedback. Audit records stay outside the policy DTO."""
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m1-n2a"))
import environment as base


@dataclass(frozen=True, slots=True)
class Power:
    id: str
    amount: int


@dataclass(frozen=True, slots=True)
class Enemy(base.Enemy):
    attack_hits: tuple[int, ...] = ()
    intents: tuple[str, ...] = ()
    powers: tuple[Power, ...] = ()


@dataclass(frozen=True, slots=True)
class Preview:
    damage_per_hit: int | None = None
    hits: int | None = None
    block: int | None = None
    draw: int | None = None


@dataclass(frozen=True, slots=True)
class Action(base.Action):
    choice: base.Card | None = None
    preview: Preview | None = None

    def native(self):
        result = super(Action, self).native()
        if self.choice is not None:
            result["choice_index"] = self.choice.index
        return result


@dataclass(frozen=True, slots=True)
class Observation(base.Observation):
    powers: tuple[Power, ...] = ()

    @classmethod
    def decode(cls, wire):
        actions = []
        for item in wire["actions"]:
            entry = dict(item)
            choice = entry.pop("choice", None)
            preview = entry.pop("preview", None)
            actions.append(Action(**entry, choice=base.Card(**choice) if choice else None,
                                  preview=Preview(**preview) if preview else None))
        enemies = tuple(Enemy(e["index"], e["hp"], e["block"], tuple(e["attack_hits"]), tuple(e["intents"]),
                              tuple(Power(**p) for p in e["powers"])) for e in wire["enemies"])
        return cls(*(wire[k] for k in ("turn", "hp", "block", "energy", "draw_count")),
                   tuple(base.Card(**card) for card in wire["hand"]), enemies, tuple(actions),
                   tuple(Power(**p) for p in wire["powers"]))


class Episode(base.Episode):
    def __init__(self, worker):
        super().__init__(worker)
        self.audit_actions = []
        self.audit_stamps = []

    def reset(self):
        self.audit_actions = []
        self.audit_stamps = []
        return super().reset()

    @property
    def observation(self):
        wire = self.state.get("observation")
        return Observation.decode(wire) if wire else None

    def step(self, action):
        if self.done or action not in self.legal_actions():
            raise ValueError("Expected an action in the current active menu")
        next_state = self.worker.request("i1_n2_step", index=action.index,
                                         position=self.state["actions"])["episode"]
        if next_state["status"] == "invalid_action":
            raise ValueError(next_state["detail"])
        advanced = next_state["actions"] > self.state["actions"]
        self.state = next_state
        self.audit_actions.append(self.state.get("audit_action") if advanced else None)
        self.audit_stamps.append(self.state.get("audit_stamp"))
        return self.observation

    def result(self):
        raw = super().result()
        return {k: v for k, v in raw.items() if k not in ("audit_action", "audit_stamp")} | {
            "feedback": feedback(raw), "audit_actions": self.audit_actions, "audit_stamps": self.audit_stamps,
        }


def feedback(raw):
    status = raw["status"]
    normal = status in ("predicted_win", "death")
    terminal = raw.get("result") if normal else None
    return {
        "status": status,
        "combat_terminal": terminal,
        "post_reward": {"executed": False, "resources": None},
        "missing_reason": None if normal else raw.get("detail") or
            (raw.get("result") or {}).get("boundary") or status,
    }


def reward(outcome, mode):
    if mode not in ("survival_only", "win_then_hp"):
        raise ValueError("Unknown reward mode")
    terminal = outcome["combat_terminal"]
    if terminal is None:
        return None
    won = outcome["status"] == "predicted_win"
    if mode == "survival_only":
        return int(won)
    return (int(won), terminal["hp"] / terminal["max_hp"] if won else 0.0)
