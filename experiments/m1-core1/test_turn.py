import gzip
import json
import unittest
from collections import Counter
import zipfile

from freeze import HERE, freeze, recipe
from policy import compile_policy
from sampled import boundary, card_type, cached_rollout, proposal


def read(name):
    raw=(HERE/"evidence"/name).read_bytes()
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


class TurnTests(unittest.TestCase):
    def test_freeze(self):
        frozen=json.loads((HERE/"benchmark.json").read_bytes())
        self.assertEqual(frozen,freeze())
        self.assertEqual(Counter(j["split"] for j in frozen["jobs"]),dict(development=24,confirmation=24))
        self.assertEqual(len({j["family"] for j in frozen["jobs"]}),48)
        self.assertEqual(len({tuple(sorted(c["id"] for c in j["spec"]["deck"])) for j in frozen["jobs"]}),48)
        for i,j in enumerate(frozen["jobs"][::2]):
            self.assertLessEqual(recipe(j,"hard",i)["hp"],24)
            self.assertEqual(recipe(j,"cross",i)["encounter"],frozen["transfer"][i%4])

    def test_exact_and_replays(self):
        for name,row in read("exact.json.gz")["rows"].items():
            with self.subTest(name=name):
                g=row["result"]
                self.assertTrue(g["invariant"])
                self.assertGreaterEqual(g["unmergedNodes"],len(g["Nodes"]))
                self.assertGreaterEqual(g["ReplayAttempts"],g["Transitions"])
                for node in g["Nodes"]:
                    if node["Kind"]=="chance":
                        self.assertAlmostEqual(sum(e["Probability"] for e in node["Edges"]),1)
                    if node["Kind"]=="B":
                        self.assertEqual(node["State"]["turn"],g["Nodes"][0]["State"]["turn"]+1)
                p=compile_policy(g,lambda kind,s:int(kind=="predicted_win"))
                self.assertAlmostEqual(sum(b["probability"] for b in p["successors"]),1)
                if name=="adapt":
                    self.assertAlmostEqual(p["value"],.5)
                    self.assertEqual({b["kind"] for b in p["successors"]},{"B","predicted_win"})
                if name=="death":
                    self.assertEqual({b["kind"] for b in p["successors"]},{"death"})
                if name=="budget":
                    self.assertLess(p["coverage"],1)
                if name=="unsupported":
                    bad=next(i for i,e in enumerate(g["Nodes"][0]["Edges"]) if e["Input"]["Card"]=="HAVOC")
                    self.assertEqual(compile_policy(g,lambda *_:1,bad)["coverage"],0)
                if name=="menu":
                    self.assertTrue(any(n["Kind"]=="choice" for n in g["Nodes"]))
                    self.assertLess(len(g["Nodes"]),g["unmergedNodes"])
                if name=="shuffle":
                    self.assertTrue(g["native"]["matched"])
                    self.assertEqual(g["native"]["LogicalShuffles"],1)

    def test_permutation_join(self):
        g=read("exact.json.gz")["rows"]["order"]["result"]
        def after(cards):
            node=g["Nodes"][0]
            for card in cards:
                edge=next(e for e in node["Edges"] if e["Input"]["Card"]==card)
                node=g["Nodes"][g["Nodes"][edge["To"]]["Edges"][0]["To"]]
            return node
        a,b="STRIKE_IRONCLAD","DEFEND_IRONCLAD"
        # Ordered discard retains the two distinct A states. After the shuffle,
        # both legal histories reach the same packed B nodes with the same masses.
        def dist(n):
            if n["Kind"]=="B":
                return {id(n):1}
            if n["Kind"]=="decision":
                self.assertEqual(len(n["Edges"]),1)
            result=Counter()
            for e in n["Edges"]:
                for leaf,w in dist(g["Nodes"][e["To"]]).items():
                    result[leaf]+=w*(e["Probability"] or 1.)
            return dict(result)
        x,y=after([a,b]),after([b,a])
        self.assertNotEqual(x["State"]["discard"],y["State"]["discard"])
        self.assertEqual(dist(x),dist(y))

    def test_no_worldwise_max(self):
        def branch(i,a):
            return dict(witness=[["h",a]],kind="B",state=str(int(i==a)),probability=.5)
        g=dict(measure="self_normalized_conditional_samples",draws=2,observations={"0":{"v":0},"1":{"v":1}},
               policies=[dict(branches=[branch(i,a) for i in range(2)]) for a in range(2)])
        p=compile_policy(g,lambda _,s:s["v"])
        self.assertEqual(p["value"],.5)
        self.assertEqual(len(p["rules"]),1)
        self.assertEqual(p["coverage"],1)

    def test_pending_boundary(self):
        st=dict(status="active")
        h=dict(turn=2,enemies=[1],decision=dict(phase="card_select"))
        self.assertIsNone(boundary(st,h,1))
        self.assertEqual(boundary(st,h|dict(decision=dict(phase="combat")),1),"B")
        self.assertNotIn(boundary(dict(status="unsupported"),None,1),("B","death","predicted_win"))

    def test_weighted_order(self):
        deck=[dict(id=c,upgrade=0) for c in "AAABC"]
        totals=Counter()
        for i in range(8000):
            order,w=proposal(deck,deck[:1],[card_type(deck[1])],str(i))
            self.assertEqual(sorted(order),list(range(5)))
            totals[tuple(deck[j]["id"] for j in order[1:])]+=w
        self.assertEqual(len(totals),12)
        self.assertLess(max(abs(v/sum(totals.values())-1/12) for v in totals.values()),.016)

    def test_cache_guard(self):
        old=dict(witness=[("r",0),("s",1)],kind="B")
        self.assertIsNone(cached_rollout([("r",0)],[old],{}))
        self.assertEqual(cached_rollout([("r",0)],[old],{((("r",0),),"s"):1}),old)

    def test_independent_donors(self):
        d=read("isolation.json")
        self.assertEqual(len(set(d["graph_hashes"])),1)
        self.assertTrue(d["distinct_donor_orders"])
        self.assertGreater(d["metrics"][1]["cached_rollouts"],0)

    def test_execution_archive(self):
        from run import diagnostic_value
        summaries=read("summary.json")
        with zipfile.ZipFile(HERE/"evidence/sampled.zip") as z:
            self.assertIsNone(z.testzip())
            for name,panel in summaries.items():
                source=json.loads(z.read(f"core1-{name}/summary.json"))
                self.assertEqual(len(source["rows"]),panel["roots"])
                successful=0
                for row in source["rows"]:
                    rec=json.loads(gzip.decompress(z.read(f"core1-{name}/{row['family']}.json.gz")))
                    for graph,ex in zip(rec["graphs"],rec["executions"]):
                        plan=compile_policy(graph,diagnostic_value)
                        self.assertEqual(plan["rules"],ex["plan"]["rules"])
                        self.assertAlmostEqual(sum(s["probability"] for s in plan["successors"]),1.)
                        self.assertIsNone(plan["unresolved_probability"])
                        successful+=ex["kind"]=="B"
                self.assertEqual(successful,panel["counts"]["executed_B"])


if __name__=="__main__":
    unittest.main()
