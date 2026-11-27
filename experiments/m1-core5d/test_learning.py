import json,unittest
from unittest.mock import patch
from torch import nn
from panel5d import E,FIVE,digest,load,rows
from fit5d import Sample,differences,torch,expected
from results5d import group,eligible
from semantic import Value
from policy5c import can_group

class Learning(unittest.TestCase):
    def test_split_and_frozen_composition(self):
        panel=load(E/"panel.gz")
        family=lambda s:{w["family"] for w in s}
        composition=lambda s:{digest(sorted(c["id"] for c in w["spec"]["deck"])) for w in s}
        self.assertEqual(len(family(panel["confirm"])),48)
        self.assertEqual(len({(w["family"],w["spec"]["seed"]) for w in panel["confirm"]}),96)
        for group in ("dev","selection","train"):
            self.assertFalse(family(panel[group]) & family(panel["confirm"]))
            self.assertFalse(composition(panel[group]) & composition(panel["confirm"]))
        self.assertFalse(family(panel["dev"]) & family(panel["selection"]))
        self.assertTrue(all(not w["spec"]["relics"] for split in panel.values() for w in split))

    def test_record_mass_and_label_assignment(self):
        observed=0
        for r in group("pairs-train-*"):
            if not eligible(r):continue
            for plan,o in zip(r["plans"],r["outcomes"]):
                self.assertAlmostEqual(sum(z[3] for z in plan["law"]),1.)
                self.assertTrue(all(z[3]>0 for z in plan["law"]))
                if o["realized"] is not None:
                    self.assertTrue(any(k=="C" and key==o["realized"] for k,key,v,p in plan["law"]))
                    observed+=1
        data=Sample().load("train").load("train2")
        self.assertEqual(len(data.distributions),data.counts["natural_C"]+observed)
        self.assertEqual(data.counts["observed_pair_C"],observed)
        self.assertEqual(len(data.pairs),244)

    def test_expected_policy_difference_and_gradient(self):
        from value import CENTERS
        net=nn.Linear(1,1+len(CENTERS),bias=False)
        data=Sample();data.states["x"]=(None,40)
        laws=[[("C","x",0,.25),("victory",None,95.,.75)],[("death",None,-50.,1.)]]
        def fake(net,data,keys):return net(torch.ones(len(keys),1))
        with patch("fit5d.logits",fake):
            prediction=differences(net,data,[(laws,70,80,12)])
        prob=fake(net,data,["x"]).softmax(-1)
        u=expected(prob,torch.tensor([70]),torch.tensor([40]),torch.tensor([80]))
        torch.testing.assert_close(prediction,.25*u+.75*95+50)
        prediction.sum().backward()
        self.assertGreater(float(net.weight.grad.abs().sum()),0.)
        exact=differences(net,data,[([[("death",None,-50.,1.)],[("victory",None,90.,1.)]],70,80,-140)])
        self.assertEqual(float(exact),-140.)
        self.assertFalse(exact.requires_grad)

    def test_low_complete_execution(self):
        audits=json.loads((E/"audit.json").read_bytes())
        for tag,expected_ids in (("rescue",{"SHRUG_IT_OFF"}),("loss",{"HEADBUTT","BATTLE_TRANCE"})):
            ws=audits["cases"][tag]["witnesses"]
            self.assertTrue(expected_ids<={w["first"] for w in ws})
            self.assertTrue(all(w["matched_C"] for w in ws))
            self.assertTrue(any(len(w["law"])>1 for w in ws))
        relic=audits["relic"]
        self.assertTrue(relic["match"] and relic["ordered_listener"])
        self.assertGreater(relic["Ordered"]["requests"],relic["Turn"]["requests"])

    def test_checkpoint_and_shared_confirm(self):
        base=torch.load(FIVE/"evidence/v2.pt",weights_only=True)
        model=torch.load(E/"v3.pt",weights_only=True)
        self.assertEqual({k:x.shape for k,x in base.items()},{k:x.shape for k,x in model.items()})
        self.assertTrue(any(not torch.equal(x,model[k]) for k,x in base.items()))
        Value().load_state_dict(model)
        for arm in ("G2","G2search","high","V1","V2","V2low","V3","V3low"):
            rs=group("confirm-"+arm+"-*")
            self.assertEqual(len(rs),96)
            self.assertTrue(all(r["terminal"] for r in rs))

    def test_conditional_world_rechecks(self):
        for probe in ("teacher","reference"):
            for path in E.glob(probe+"-*.gz"):
                for r in load(path):
                    if len(r["worlds"])!=4:continue
                    for w in r["worlds"]:
                        self.assertEqual(len(set(w["order"])),len(w["order"]))
                        self.assertTrue(eligible(w))
                    first,second=r["worlds"][:2],r["worlds"][2:]
                    self.assertFalse({tuple(w["order"]) for w in first}&{tuple(w["order"]) for w in second})

    def test_native_chapter_distribution(self):
        panel=json.loads((E/"relic-panel.json").read_bytes())
        for act in (1,2,3):
            roots=[r for r in panel["roots"] if r["act"]==act]
            self.assertAlmostEqual(sum(r["weight"] for r in roots),1/3)
            witness=next(r for r in panel["replay"] if r["act"]==act)
            self.assertTrue(witness["map_restore"] or witness.get("full_prefix"))
        self.assertEqual(len({r["key"] for r in panel["roots"]}),len(panel["roots"]))
if __name__=="__main__":unittest.main()
