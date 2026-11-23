"""Regressions for legal action binding and narrow deterministic labels."""
import numpy as np
import torch

from features import Encoder, MASSIVE_HP
from labels import scoped_order, transition_summary
from network import Network
from prepare import collate
from train import objectives


def observation(enemy_hp=40):
    def card(i, name):
        return dict(index=i,id=name,upgrade=0,cost=1,enchantment=None,enchantment_amount=None,
                    affliction=None,affliction_amount=None)

    def action(i, kind, card_slot=None, target=None):
        return dict(index=i,kind=kind,card=card_slot,target=target,choice=None,
                    cost=1 if card_slot is not None else None,
                    target_side="enemy" if target is not None else None,energy_x=False,preview=None)

    deck = [card(0,"INFLAME"), card(1,"TWIN_STRIKE")]
    return dict(decision=dict(phase="combat"),deck=deck,hand=deck,discard=[],exhaust=[],
                actions=[action(0,"play_card",0), action(1,"play_card",1,0),action(2,"end_turn")],
                enemies=[dict(index=0,hp=enemy_hp,block=0,powers=[],attack_hits=[5],intents=["Attack"])],
                hp=60,max_hp=80,energy=3,block=0,draw_count=7,turn=1,powers=[],relics=[],potions=[],stars=0)


def as_tensors(records):
    return {k:torch.from_numpy(v) for k,v in collate(records).items()}


def test_scoped_order_lethal_and_energy_reversal():
    assert scoped_order(observation()) == (0,1)
    assert scoped_order(observation(8)) == (1,0)
    assert scoped_order(observation() | {"energy":1}) is None
    assert scoped_order(observation(MASSIVE_HP)) is None


def test_sentinel_and_unknown_preserve_explicit_features():
    encoder = Encoder(["INFLAME"])
    obs = observation(999999999)
    x = encoder.encode(obs,encoder.initial_history())
    assert transition_summary(obs)[5] == 0
    assert x["enemies"][1,4] == 1
    assert np.abs(x["enemies"]).max() <= 10
    assert 1 in x["cards"]


def test_legal_logits_ignore_batch_padding_and_hand_presentation():
    torch.manual_seed(11)
    vocabulary = ["INFLAME","TWIN_STRIKE"]
    encoder = Encoder(vocabulary)
    net = Network(vocabulary).eval()
    obs = observation()
    memory = encoder.initial_history()
    original = encoder.encode(obs,memory)
    moved = encoder.encode(obs | {"hand":obs["hand"][::-1]},memory)
    restricted = encoder.encode(obs | {"actions": [dict(obs["actions"][2],index=0)]},memory)
    with torch.inference_mode():
        logits = net(as_tensors([original,moved,restricted]))
    torch.testing.assert_close(logits[0],logits[1],atol=2e-6,rtol=0)
    assert torch.isfinite(logits[2,0])
    assert torch.isneginf(logits[2,1:]).all()


def test_behavior_loss_ignores_p0_action_label():
    torch.manual_seed(11)
    vocabulary = ["INFLAME","TWIN_STRIKE"]
    encoder = Encoder(vocabulary)
    net = Network(vocabulary)
    feature = encoder.encode(observation(),encoder.initial_history())
    labels = dict(chosen=0,source=0,pair=(0,1),order=np.float32(1),order_mask=True,
                  delta=np.zeros(16,np.float32),delta_mask=True,outcome=np.zeros(6,np.float32))
    weak = feature | labels
    teacher = weak | {"source":1,"chosen":1}
    first,_ = objectives(net,as_tensors([weak,teacher]),[1,1,1,1],"behavior")
    second,_ = objectives(net,as_tensors([weak | {"chosen":2},teacher]),[1,1,1,1],"behavior")
    torch.testing.assert_close(first,second,atol=0,rtol=0)
