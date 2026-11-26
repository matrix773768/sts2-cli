import numpy as np
import unittest
import torch

from arena import PARENT, ROOT, load, manifest, project, tensors
from mechanics import PilotEncoder, extend
from sv_data import Encoder
from value import targets


def public():
    card=dict(index=0,id="STRIKE_IRONCLAD",upgrade=0,cost=0)
    enemy=dict(index=0,hp=20,block=0,attack_hits=[2,5],intents=["Attack"],powers=[])
    action=dict(index=0,kind="play_card",card=0,choice=None,target=0,target_side="enemy",cost=0)
    return dict(decision=dict(phase="combat"),hp=50,max_hp=80,turn=2,energy=2,block=0,
                stars=0,potions=[],relics=[],draw_count=3,deck=[card],hand=[card],
                discard=[],exhaust=[],enemies=[enemy],actions=[action],powers=[],
                mechanism=dict(played=2,attacks=1,skills=1,species=["FUZZY_WURM_CRAWLER"],
                               stacks=[dict(owner=0,id="ARTIFACT_POWER",amount=2)]))


class Tests(unittest.TestCase):
    def test_hidden_fields_excluded_and_entity_alignment(self):
        obs=public()
        original=lambda raw:{k:v for k,v in raw.items() if k in ("enemies","hand")}
        polluted=obs | dict(actual_draw_order=[7,3], seed="private",
                            mechanism=obs["mechanism"] | dict(next_move="secret"))
        assert project(original,polluted)==project(original,obs)
        with self.assertRaises(ValueError):
            project(original, obs | dict(mechanism=obs["mechanism"] | dict(species=[])))


    def test_state_changes_survive_extended_encoding_only(self):
        obs=public()
        alt=obs | dict(mechanism=obs["mechanism"] | dict(played=5,stacks=[]))
        for active in (False,True):
            enc=PilotEncoder(["STRIKE_IRONCLAD"],active)
            x,y=[enc.encode(o,enc.initial_history()) for o in (obs,alt)]
            assert np.array_equal(x["enemies"],y["enemies"]) != active
            assert np.array_equal(x["player"],y["player"]) != active


    @unittest.skipUnless(PARENT.is_file(), "local frozen G2 required")
    def test_zero_columns_preserve_all_parent_distributions(self):
        net,meta=load(PARENT)
        obs=public()
        def score(enc):
            row=enc.encode(obs,enc.initial_history()) | dict(policy=0)
            with torch.no_grad():
                return net(tensors([row],"cpu"))
        old=score(Encoder(meta["vocabulary"]))
        extend(net)
        new=score(PilotEncoder(meta["vocabulary"],True))
        for a,b in zip(old,new,strict=True):
            torch.testing.assert_close(a,b,atol=2e-5,rtol=1e-5)


    def test_family_split_and_signed_terminal_classes(self):
        if (ROOT/"logs/m1-dc1-formal/roots/train.json").exists():
            jobs=manifest()["jobs"]
            assert len(jobs)==len({j[1]["seed"] for j in jobs})==len({j[3] for j in jobs})==232
        cls=targets(torch.tensor([50]*4),torch.tensor([0,55,50,45]),torch.tensor([True,False,False,False]))
        assert 0==cls[0]<cls[1]<cls[2]<cls[3]
