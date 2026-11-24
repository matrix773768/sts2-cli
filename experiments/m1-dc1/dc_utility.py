"""DC1 utility candidates and label reconstruction from exact recorded outcomes."""
from functools import partial
from math import log1p
from pathlib import Path
from types import FunctionType

import numpy as np
import torch

from dc_common import checksum, config, digest
import loop_battle
from loop_policy import NetworkPolicy
from sv_data import outcome
from sv_runtime import tensors

# Centers of signed/unsigned bins are shared near zero. Values outside the
# last center remain overflow rather than being silently clamped.
LOSS_CENTERS = tuple(range(0, 21)) + (24, 28, 32, 36, 40, 48, 56, 64, 80, 96, 128, 160, 256, 512, 768, 1024, 1536, 2048)
NET_CENTERS = tuple(-x for x in reversed(LOSS_CENTERS[1:])) + LOSS_CENTERS


def loss_curve(loss, kappa=10., linear_weight=.05, normalized=True):
    value = kappa * log1p(loss / kappa) + linear_weight * loss
    return value / (1 + linear_weight) if normalized else value


def bin_center(value, centers):
    from bisect import bisect_left
    if value is None or not centers[0] <= value <= centers[-1]:
        return None
    i = bisect_left(centers, value)
    if i == 0:
        return centers[0]
    return min(centers[i-1:i+1], key=lambda n: abs(n-value))


def labels(row):
    final = row["terminal"]
    start = row["root"]
    net = start["hp"] - final["hp"]
    damage = row.get("cumulative_loss")
    return dict(death=row["status"] == "death", old_class=outcome(row, 32),
                start_hp=start["hp"], start_max_hp=start["max_hp"],
                end_hp=final["hp"], end_max_hp=final["max_hp"],
                max_hp_delta=final["max_hp"] - start["max_hp"],
                net_loss=net, cumulative_loss=damage, healing=row.get("cumulative_healing"),
                hp_credit=damage-net if damage is not None else None,
                net_bin=bin_center(net, NET_CENTERS), cumulative_bin=bin_center(damage, LOSS_CENTERS),
                gold=final.get("gold"), potions=final.get("potions"), turns=final["turn"])


def observed_utilities(label, cfg):
    hp_scale, kappa, weight = (cfg[k] for k in ("hp_scale", "kappa", "linear_weight"))
    death, net, damage = (label[k] for k in ("death","net_loss","cumulative_loss"))
    return dict(
        U0=-1. if death else 1 + .25*label["end_hp"]/label["end_max_hp"],
        U1=-1. if death else 1 - .25*net/hp_scale,
        U2=None if damage is None else (-1. if death else 1.) - .25*loss_curve(damage,kappa,weight)/hp_scale,
        historical=(-50. if death else 100.) - loss_curve(max(0,net),kappa,weight,False) - .2*label["turns"])


def risk_order(death, expected_hp, threshold):
    allowed = death <= threshold
    # Order feasible choices by expected remaining HP. If the constraint
    # cannot be met, fall back to minimum predicted death risk.
    return np.lexsort((np.arange(len(death)), -expected_hp, np.where(allowed, 0., death), ~allowed))


class UtilityPolicy(NetworkPolicy):
    def __init__(self, weights, continuation, budget, epsilon, host_id, cfg, *, utility):
        if budget or epsilon or utility not in ("U1", "U3"):
            raise ValueError("DC1 utility experiment uses frozen direct Q")
        super().__init__(weights, continuation, budget, epsilon, host_id, cfg)
        self.utility = utility
        self.utility_cfg = config()["utility"]
        self.definition.update(utility=utility, utility_parameters=self.utility_cfg,
                               utility_source=checksum(Path(__file__)), approximation="SV3A ratios and conditional mean max HP")
        self.identity = digest(self.definition)

    @torch.inference_mode()
    def forward(self, requests):
        rows = [row for (block,) in requests for row in block]
        result = []
        for offset in range(0, len(rows), 128):
            chunk = rows[offset:offset+128]
            batch = tensors(chunk, "cpu")
            _, output = self.net(batch)
            probability = self.net.probabilities(output)
            # PRE1 public vector begins with HP ratio, and has the current
            # max HP scaled by 1000 after the eight summary and five power fields.
            public_max_hp = batch["player"][:,13] * 1000
            public_hp = batch["player"][:,0] * public_max_hp
            current_max = public_max_hp[:,None]
            hp = self.net.expected_hp(output, current_max)
            win = 1-probability[...,0]
            loss_if_win = win*public_hp[:,None]-hp
            u1 = -probability[...,0]+win-.25*loss_if_win/self.utility_cfg["hp_scale"]
            for row, probs, expected, values in zip(chunk, probability.numpy(), hp.numpy(), u1.numpy(), strict=True):
                n = len(row["actions"])
                probs = probs[:n]
                if self.utility == "U3":
                    order = risk_order(probs[:,0], expected[:n], self.utility_cfg["risk_threshold"])
                    scores = np.empty(n, dtype=np.float32)
                    scores[order] = np.arange(n,0,-1,dtype=np.float32)
                else:
                    scores = values[:n]
                result.append((scores, probs))
        start = 0
        for block, in requests:
            yield result[start:start+len(block)]
            start += len(block)


def run_utility(utility, *args):
    # Bind the policy factory to this invocation. The original SV4A module
    # and ledgers retain their exact source and policy hashes.
    runner = FunctionType(loop_battle.run.__code__, loop_battle.run.__globals__ |
                          {"NetworkPolicy": partial(UtilityPolicy, utility=utility)},
                          argdefs=loop_battle.run.__defaults__)
    return runner(*args)
