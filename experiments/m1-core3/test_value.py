import unittest
from value_net import *
from experience import read
import json,gzip
E=HERE/"evidence"
class ValueLearning(unittest.TestCase):
    def test_family_and_censoring(self):
        rows=[json.loads(l) for f in E.glob("fights*.gz") for l in gzip.open(f)]
        self.assertEqual((len(rows),len({r["ordinal"] for r in rows})),(1024,1024))
        groups={}
        for r in rows:
            self.assertEqual(groups.setdefault(r["family"],r["split"]),r["split"])
            self.assertEqual(r["policy"],"frozen-G2")
            if r.get("terminal") is None:self.assertNotIn(r.get("status"),("death","predicted_win"))
            for c in r["states"]:
                self.assertFalse(c["enemy_models"]);self.assertEqual(c["setup"]["stage"],"before_initial_draw")
        self.assertEqual(len(groups),512)

    def test_signed_root_accounting(self):
        for current,end in [(60,70),(80,70),(55,45)]:
            p=torch.zeros(1,1+len(CENTERS));p[0,1+CENTERS.index(current-end)]=1
            self.assertAlmostEqual(expected(p,torch.tensor(85),torch.tensor([current]),torch.tensor(80)).item(),
                                   payoff(torch.tensor(85-end),torch.tensor(80)).item(),places=4)
        p.zero_();p[0,0]=1
        self.assertEqual(expected(p,torch.tensor(85),torch.tensor([60]),torch.tensor(80)).item(),-50.)

    def test_models_and_mechanism_difference(self):
        d=read(E/"fit.json");self.assertEqual(d["selected"],min(d["arms"],key=lambda k:d["arms"][k]["best"]))
        for arm in d["arms"]:
            net=network(arm);net.load_state_dict(torch.load(E/(arm+".pt"),weights_only=True))
        p=read(E/"diagnostics.json")["probes"]
        self.assertEqual(p["persistent"]["simple"],p["growth"]["simple"])
        self.assertNotEqual(p["persistent"]["mechanism"],p["growth"]["mechanism"])

    def test_chance_policy_is_public(self):
        a,b=read(E/"draw.json")["rows"]
        self.assertEqual(a["root"],b["root"]);self.assertEqual(a["options"],b["options"])
        self.assertEqual(a["law"],{"STRIKE_IRONCLAD#0":1/3,"BLUDGEON#0":2/3})
        self.assertEqual((a["reason"],b["reason"]),("terminal","end"))

    def test_worlds_and_results(self):
        for f in E.glob("*audit.gz"):
            a=json.load(gzip.open(f))
            for row in a["rows"]:
                for worlds in row["blocks"].values():
                    for w in worlds:
                        self.assertEqual(set(w["outcomes"]),set(row["actions"]))
                        for outcome in w["outcomes"].values():
                            c=outcome.get("boundary")
                            if c:self.assertFalse(c["enemy_models"])
                self.assertLessEqual(row["search"]["visited_A"],48)
        m=read(E/"results.json")
        self.assertLessEqual(m["results"]["teacher"]["interval"][0],0)
        self.assertEqual(m["results"]["confirmation_model"]["n"],12)
if __name__=="__main__":unittest.main()
