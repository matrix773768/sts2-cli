"""Policy-conditioned distribution of absolute future net HP loss."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-dc1"))
from dc_common import ROOT, checksum
from sv_model import ValueNet, load as load_parent

import torch
from torch import nn

VERSION = "sts2.dc2b.absolute-net.v1"
POSITIVE = (*range(21), *range(25,51,5), *range(60,101,10), *range(125,201,25),
            250, 320, 420, 560, 750, 999, 1400, 2000)
CENTERS = (*(-x for x in reversed(POSITIVE[1:])), *POSITIVE)


def targets(current_hp, end_hp, death):
    centers = current_hp.new_tensor(CENTERS)
    delta = current_hp - end_hp
    if ((~death) & ((delta.abs() > centers[-1]))).any():
        raise ValueError("Victory net loss outside supported tail; revise representation explicitly")
    return torch.where(death, 0, 1+(delta[...,None]-centers).abs().argmin(-1))


def payoff(loss, initial_max):
    positive = loss.clamp_min(0)
    mixed = 10*torch.log1p(positive/10)+.05*positive + loss.clamp_max(0)
    mix = torch.where(initial_max >= 500, 1., torch.where(initial_max > 100, .5, 0.))
    return 100 - ((1-mix)*loss+mix*mixed).clamp_max(149)


def expected(prob, initial_hp, current_hp, initial_max):
    centers = prob.new_tensor(CENTERS)
    values = payoff((initial_hp-current_hp)[...,None]+centers, initial_max[...,None])
    return -50*prob[...,0]+(prob[...,1:]*values).sum(-1)


class Net(ValueNet):
    def __init__(self, vocabulary, width, policy_slots):
        super().__init__(vocabulary,width,len(CENTERS),policy_slots)
        del self.fractions
        for head in (self.v,self.q):
            last = head[-1]
            head[-1] = nn.Linear(last.in_features,1+len(CENTERS))

    def probabilities(self, outcome):
        return outcome.softmax(-1)


def initialize(path, extra_slots=32):
    parent, saved = load_parent(path)
    spec = {"width":saved["spec"]["width"], "policy_slots":extra_slots}
    net = Net(saved["vocabulary"],**spec)
    net.encoder.load_state_dict(parent.encoder.state_dict())
    with torch.no_grad():
        net.policy.weight[:len(saved["policies"])].copy_(parent.policy.weight[:len(saved["policies"])])
        for new,old in ((net.v,parent.v),(net.q,parent.q)):
            new[:-1].load_state_dict(old[:-1].state_dict())
    meta = dict(version=VERSION,spec=spec,vocabulary=saved["vocabulary"],policies=list(saved["policies"]),
                parent=checksum(path),centers=list(CENTERS))
    return net, meta


def load(path):
    saved = torch.load(path,map_location="cpu",weights_only=True)
    if saved["version"] != VERSION or saved["centers"] != list(CENTERS):
        raise ValueError("DC2B checkpoint contract mismatch")
    net = Net(saved["vocabulary"],**saved["spec"])
    net.load_state_dict(saved["model"])
    return net.eval(), saved
