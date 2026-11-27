import gzip,json,unittest
from collections import Counter
from itertools import permutations
from panel5c import E,HERE,FIVE
from policy5c import events
from backup5c import combine

def read(name):
    with gzip.open(E/name) if name.endswith(".gz") else open(E/name) as f:
        return json.load(f)

class Completion(unittest.TestCase):
    def test_multisets_against_labeled_draws(self):
        for deck in ("AAB","ABBC","AABBCD","ABCD"):
            pool=Counter(deck)
            for n in range(1,len(deck)+1):
                expected=Counter()
                for seq in permutations(range(len(deck)),n):
                    bag=sorted(deck[i] for i in seq)
                    remain=pool.copy()
                    tokens=[]
                    for k in bag:
                        if len(remain)>1:
                            tokens.append(k)
                        remain[k]-=1
                        if not remain[k]:
                            del remain[k]
                    expected[tuple(tokens)]+=1
                total=sum(expected.values())
                actual=dict(events(pool,n))
                self.assertEqual(actual.keys(),expected.keys())
                for key,count in expected.items():
                    self.assertAlmostEqual(actual[key],count/total)
    def test_late_public_switch(self):
        def row(obs,action,value,p):
            path=(("root","top",False),("selector","pick",False),("after","draw",False),(obs,action,True))
            return p,"C",value,path
        left=[row("A","block",8,.25),row("B","block",0,.75)]
        right=[row("A","attack",-2,.25),row("B","attack",5,.75)]
        score=lambda rows:(1.,sum(p*v for p,k,v,path in rows),{})
        result=combine([left,right],score)
        self.assertEqual(result,[left[0],right[1]])
    def test_natural_witnesses(self):
        for tag in ("rescue","loss"):
            d=read(f"witness-{tag}.gz")
            native=read(f"native-{tag}.json")
            self.assertTrue(native["query"]["use"] and native["query"]["conditional"])
            self.assertEqual(native["actual"]["hp"],28 if tag=="loss" else 1)
            self.assertEqual(native["actual"]["decision"],"card_reward")
            for r in d["results"]:
                self.assertAlmostEqual(sum(r["mass"].values()),1.)
                if r["coverage"]>=1-1e-9:
                    self.assertTrue(r["matched_c"])
            if tag=="loss":
                line=next(r for r in d["results"] if r["first"]["card"]["id"]=="HEADBUTT" and r["first"]["target"]==0 and r["style"]=="block")
                self.assertEqual(line["actions"][1]["pick"]["id"],"IMPERVIOUS")
                self.assertEqual([a["card"] for a in line["actions"] if a["kind"]=="play_card"],["HEADBUTT","BATTLE_TRANCE","IMPERVIOUS"])
                baseline=json.loads(gzip.decompress((HERE.parent/"m1-core5b/evidence/turn-probe-loss.gz").read_bytes()))
                for i,name in enumerate(("v1","v2")):
                    self.assertAlmostEqual(line[name],baseline["lines"]["head_combo"]["v"][i],places=4)
            else:
                line=next(r for r in d["results"] if r["style"]=="repeat")
                self.assertEqual([a["card"] for a in line["actions"] if a["kind"]=="play_card"],["SHRUG_IT_OFF","DEFEND_IRONCLAD","DEFEND_IRONCLAD"])
                self.assertEqual(line["status"],"death")
    def test_kernel_and_mass(self):
        cases=read("mechanisms.json")["cases"]
        self.assertGreater(len(cases["INFERNAL_BLADE"]["outcomes"]),1)
        self.assertEqual(len(cases["SWORD_BOOMERANG"]["outcomes"]),1)
        self.assertEqual(len(cases["TRUE_GRIT"]["exhaust"]),1)
        ordered=read("stress-ordered-4096.json")["policies"]
        merged=read("stress-multiset-4096.json")["policies"]
        for k in ordered:
            self.assertEqual((ordered[k]["leaves"],merged[k]["leaves"]),(60,10))
            self.assertEqual(ordered[k]["law"].keys(),merged[k]["law"].keys())
            for key,p in ordered[k]["law"].items():
                self.assertAlmostEqual(p,merged[k]["law"][key])
            self.assertAlmostEqual(sum(merged[k]["law"].values()),1.)
        for r in read("stress-ordered-32.json")["policies"].values():
            self.assertGreater(r["law"]["budget"],0)
            self.assertAlmostEqual(r["mass"],1.)
    def test_frozen_panel_and_execution(self):
        panel=read("protocol.gz")
        fresh=panel["fresh"]
        deck=lambda s:tuple(sorted(c["id"] for c in s["deck"]))
        compositions={deck(w["spec"]) for w in fresh}
        self.assertEqual(len(compositions),48)
        self.assertEqual(set(Counter(w["family"] for w in fresh).values()),{2})
        old=json.loads(gzip.decompress((FIVE/"evidence/panels.gz").read_bytes()))
        prior=json.loads(gzip.decompress((HERE.parent/"m1-core5b/evidence/panel.gz").read_bytes()))
        self.assertFalse(compositions & ({deck(j[1]) for jobs in old.values() for j in jobs}|{deck(w["spec"]) for w in prior["fresh"]}))
        for arm in panel["arms"]:
            roots=[]
            for f in E.glob("fresh-"+arm+"*.gz"):
                with gzip.open(f) as stream:
                    for r in map(json.loads,stream):
                        roots.append((r["family"],r["seed"]))
                        self.assertIsNotNone(r["terminal"])
                        for q in r["queries"]:
                            self.assertAlmostEqual(sum(q["candidate_mass"].values()),1.)
                            self.assertAlmostEqual(sum(q["reference_mass"].values()),1.)
                            self.assertEqual(q["used"],min(q["coverage"],q["reference_coverage"])>=1-1e-9 and q["value"]>q["reference"]+1.)
                            if q["used"]:
                                self.assertIn(q["result"],("end","terminal"))
            self.assertCountEqual(roots,[(w["family"],w["spec"]["seed"]) for w in fresh])
if __name__=="__main__":
    unittest.main()
