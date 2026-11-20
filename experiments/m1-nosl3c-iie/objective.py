"""Versioned terminal-only net HP objective."""
from dataclasses import dataclass
from math import isfinite, log1p

VERSION = "sts2.nosl.hp-loss.v1"


@dataclass(frozen=True)
class Objective:
    mode: str
    kappa: float
    linear_weight: float
    win_bonus: float
    death_penalty: float
    turn_cost: float

    def __post_init__(self):
        values = (self.kappa, self.linear_weight, self.win_bonus, self.death_penalty, self.turn_cost)
        if (self.mode not in ("linear", "log", "mixed") or not all(isfinite(v) for v in values)
                or self.kappa <= 0 or min(values[1:]) < 0 or self.win_bonus <= 0):
            raise ValueError("Invalid HP objective")

    def loss(self, damage):
        if not isfinite(damage) or damage < 0:
            raise ValueError("Expected finite nonnegative HP loss")
        if self.mode == "linear":
            return damage
        # For very small kappa the division can overflow before the logarithm.
        ratio = damage / self.kappa
        if not isfinite(ratio):
            from math import log
            smooth = self.kappa * (log(damage) - log(self.kappa))
        else:
            smooth = self.kappa * log1p(ratio)
        return smooth + (self.linear_weight * damage if self.mode == "mixed" else 0)

    def reward(self, feedback, hp_start):
        if not feedback["eligible"] or feedback["status"] not in ("predicted_win", "death"):
            return None
        final = feedback["observation"]
        net = max(0, hp_start - final["hp"])
        reward = (self.win_bonus if feedback["status"] == "predicted_win" else -self.death_penalty)
        return reward - self.loss(net) - self.turn_cost * final["turn"]
