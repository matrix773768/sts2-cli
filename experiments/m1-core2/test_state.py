import unittest
from core2_dataset import *

E=HERE/"evidence"

class StrategicState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(E/"diagnostics.json.gz","rt") as f:cls.d=json.load(f)["rows"]

    def test_equal_cost_distinct_expiry(self):
        x=self.d["cost"]
        self.assertEqual([v["cost"] for v in x["before"]],[0,0])
        self.assertNotEqual(*[v["layers"] for v in x["before"]])
        self.assertEqual([v["cost"] for v in x["after"]],[2,1])

    def test_equal_strength_different_growth(self):
        def strength(c):return next((p["amount"] for p in c["powers"] if p["id"]=="STRENGTH_POWER"),0)
        for key,expected in [("growth",[0,3,6]),("persistent",[3,3,3])]:
            states=[r["C"] for r in self.d[key] if r["C"]]
            self.assertEqual([strength(c) for c in states],expected)
            self.assertTrue(all(p["rule_ref"] for c in states for p in enrich(c)["supply"]))

    def test_cross_turn_and_zones(self):
        d=self.d
        self.assertEqual((d["disarm"][0]["B"]["enemies"][0]["attack_hits"],d["disarm"][1]["C"]["hp"]),([0],80))
        self.assertEqual(d["control"][0]["C"]["hp"],76)
        self.assertEqual(d["disarm"][-1]["C"]["hp"]-d["control"][-1]["C"]["hp"],4)
        top=d["headbutt"][2]
        self.assertEqual(top["C"]["deck"],d["strike"][1]["C"]["deck"])
        self.assertEqual(top["C"]["belief"]["top"],["STRIKE_IRONCLAD#0"])
        self.assertEqual(d["strike"][1]["C"]["belief"]["top"],[])
        self.assertEqual(top["B"]["hand"][0]["id"],"STRIKE_IRONCLAD")
        self.assertEqual([d[k][0]["B"]["energy"] for k in ("strike","threshold")],[2,3])

    def test_conditioned_future(self):
        m=json.loads((E/"summary.json").read_bytes())
        a,b=m["attack_contrast"]
        self.assertEqual(a["hits"],b["hits"])
        self.assertNotEqual(a["next_hits"],b["next_hits"])
        self.assertGreater(m["windows_narrowed"],0)
        self.assertEqual(*m["observed_next_in_window"])

    def test_labels_and_provenance(self):
        rows=[r for group in learning_batches(E/"records.jsonl.gz",7) for r in group]
        self.assertEqual((len(rows),len({r["family"] for r in rows})),(131,24))
        for r in rows:
            c=r["input"]["state"]
            t=r["target"]["terminal"]
            self.assertEqual(c["schema"],"sts2.core.c.v3")
            self.assertFalse(c["enemy_models"])
            self.assertEqual(r["target"]["net_hp"],c["hp"]-t["hp"])
            self.assertLess(r["past"][-1][0]["turn"],c["turn"])
            self.assertTrue(all(k in t for k in ("hp","max_hp","gold","potions")))
        strict=[r for g in strict_batches(11) for r in g]
        self.assertEqual(len(strict),56)
        self.assertAlmostEqual(sum(x["weight"] for r in strict for x in r["distribution"] if x["qualification"]=="C"),47)
        for r in strict:self.assertAlmostEqual(sum(x["weight"] for x in r["distribution"]),1)
        proxy=[x for g in batches(E/"records.jsonl.gz") for r in g for x in r.get("distribution",[]) if x["qualification"]=="C_model"]
        self.assertTrue(proxy and all(not x["strict_input"] for x in proxy))

    def test_native_terminal(self):
        native=json.loads((E/"native.json").read_bytes())
        self.assertEqual([r["result"]["terminal_match"] for r in native["rows"]],[True,True])

if __name__=="__main__":unittest.main()
