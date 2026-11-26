from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch
from assessment import rows,load_value
from semantic import *
from core4_roots import panels

E=HERE/"evidence"

class CombatLoop(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=next(rows(E/"on0.gz"))["states"][0]

    def test_no_species_or_global_move_identity(self):
        c=deepcopy(self.c);e=c["enemies"][0]
        c["enemies"]=[e];e["move"]="a";e["phase"].update(node="a",committed_moves=["a"],repeat_windows={})
        n=dict(MoveId="a",BaseDamage=8,Repeats=1,next="b",attacks=[],effects=[],targets=[])
        other=n|dict(MoveId="b",next="a",BaseDamage=17)
        rules=static_rules()|dict(graphs={e["species"]:[n,other]})
        with patch("semantic.static_rules",return_value=rules):left=encode(c)
        e.update(species="alias",move="first")
        e["phase"].update(node="first",rule_ref="alias",committed_moves=["first"])
        rules["graphs"]={"alias":[n|dict(MoveId="first",next="last"),other|dict(MoveId="last",next="first")]}
        with patch("semantic.static_rules",return_value=rules):right=encode(c)
        for a,b in zip(left,right):np.testing.assert_array_equal(a,b)

    def test_semantic_differences(self):
        c=deepcopy(self.c);foe=c["enemies"][0];foe["attack_hits"]=[4,9]
        a=encode(c)[1];foe["attack_hits"].reverse();b=encode(c)[1]
        idx=(a[:,F["actual"]]>0)&(a[:,F["order"]]==np.float32(np.log(2)))
        self.assertFalse(np.array_equal(a[idx],b[idx]))
        card=c["card_state"]["discard"][0]
        card["cost_layers"]["energy"]=[dict(amount=0,expires="UntilTurnEnds")]
        a=encode(c)[1];card["cost_layers"]["energy"][0]["expires"]="UntilPlayed"
        b=encode(c)[1];self.assertFalse(np.array_equal(a[:,F["until_play"]],b[:,F["until_play"]]))
        c["belief"]["top"].append(card["type"])
        self.assertEqual(len(encode(c)[1]),len(b)+1)

    def test_discard_order_and_batch(self):
        c=deepcopy(self.c);net=load_value(E/"v1.pt");before=encode(c)
        c["card_state"]["discard"].reverse()
        with torch.no_grad():a,b=net(*pack([before,encode(c)])).softmax(-1)
        torch.testing.assert_close(a,b);self.assertAlmostEqual(a.sum().item(),1,places=5)

    def test_proxy_and_wrong_boundary(self):
        for c in (self.c|dict(enemy_models=["proxy"]),self.c|dict(setup={"stage":"after_draw"})):
            with self.assertRaises(ValueError):encode(c)

    def test_rollout_separation_and_confirmation(self):
        groups=panels();ids={k:{j[3] for j in v} for k,v in groups.items()}
        self.assertEqual([len(ids[k]) for k in ("train","dev","confirm")],[408,52,100])
        self.assertEqual(len(set.union(*ids.values())),560)
        reserved={j["family"] for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"]}
        self.assertFalse(set.union(*ids.values())&reserved)
        natural=[(r["family"],r["seed"]) for f in E.glob("nat*.gz") for r in rows(f)]
        self.assertEqual(len(set(natural)),1632)
        keys=None
        for arm in ("G2","G2search","core3","v0","v1"):
            records=[r for f in E.glob("test-"+arm+"-*.gz")for r in rows(f)]
            self.assertEqual({r["family"] for r in records},ids["confirm"])
            paired={(r["family"],r["seed"]) for r in records}
            if keys is None:keys=paired
            self.assertEqual(keys,paired)
            for r in records:
                for q in r["queries"]:
                    if arm in ("v0","v1") and q["used"]:
                        self.assertGreaterEqual(min(q["reference_coverage"],q["coverage"]),1-1e-9)
                        self.assertGreater(q["value"]-q["reference"],1)
