import gzip
import json
import os
from pathlib import Path
import unittest
import zipfile

from archive import metrics
from build import source_sha
from search import belief,frontier_witnesses,is_next_decision,policy,strategic_successors

HERE=Path(__file__).resolve().parent
EVIDENCE=Path(os.environ.get("CORE1R_EVIDENCE",HERE/"evidence"))


def paths(graph,i=0,prefix=()):
    node=graph["nodes"][i]
    yield prefix,node
    if node["kind"]=="decision":
        for edge in node["edges"]:
            card=node["state"]["hand"][edge["input"]["card"]]
            yield from paths(graph,edge["to"],(*prefix,card["id"]))


class Results(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads(gzip.decompress((EVIDENCE/"fixtures.json.gz").read_bytes()))["rows"]

    def test_emitted_front_has_witnesses_and_matches_exhaustion(self):
        self.assertEqual(len(self.rows),11)
        for name,row in self.rows.items():
            with self.subTest(name=name):
                tree,red=(row["graphs"][k] for k in ("tree","reduced"))
                self.assertFalse(set(tree["counts"]) & {"budget","depth_cap","draw_depth_cap"})
                front={tuple(w["joint"]) for w in frontier_witnesses(red)}
                self.assertEqual(front,set(map(tuple,tree["no_draw_front"])))
                self.assertLess(red["calls"],tree["calls"])
                for w in frontier_witnesses(red):
                    i=0
                    for step in w["route"]:
                        i=next(e["to"] for e in red["nodes"][i]["edges"] if e["input"]["index"]==step["action"])
                    self.assertEqual(red["nodes"][i]["joint"],w["joint"])
                    self.assertEqual(w["state"]["actions"][w["end"]]["kind"],"end_turn")

    def test_upgrade_dominance_before_simulation(self):
        graphs=self.rows["upgrade"]["graphs"]
        self.assertEqual([graphs[k]["calls"] for k in ("tree","no_dominance","reduced")],[85,18,8])
        root=graphs["reduced"]["nodes"][0]
        self.assertTrue(all(root["state"]["hand"][e["input"]["card"]]["upgrade"]==1 for e in root["edges"]))

    def test_joint_target_allocation(self):
        g=self.rows["multi_target"]["graphs"]["reduced"]
        start=g["nodes"][0]["joint"]
        self.assertEqual(len(start),8)
        allocation={(p[6]-start[6],p[7]-start[7]) for p in g["no_draw_front"]}
        self.assertTrue(any(x>0 and y>0 for x,y in allocation))
        self.assertTrue(any(x>0 and y==0 for x,y in allocation))
        self.assertTrue(any(x==0 and y>0 for x,y in allocation))

    def test_precedence_preserves_optional_subsets(self):
        for name,buff,basic in [("strength","INFLAME","STRIKE_IRONCLAD"),("dexterity","FOOTWORK","DEFEND_SILENT"),
                                ("vulnerable","BASH","STRIKE_IRONCLAD")]:
            graph=self.rows[name]["graphs"]["reduced"]
            moves=list(paths(graph))
            self.assertTrue(any(p==(buff,) for p,_ in moves))
            self.assertTrue(any(p==(basic,) for p,_ in moves))
            self.assertTrue(any(buff in p and basic in p for p,_ in moves))
            for p,_ in moves:
                if buff in p and basic in p: self.assertLess(p.index(buff),p.index(basic))
            self.assertGreater(graph["counts"]["precedence_constraints"],0)

    def test_active_relic_resolution(self):
        for name,mechanism,card,idx,expected in [("nunchaku","NUNCHAKU@9","STRIKE_IRONCLAD",2,3),
                                                 ("fork","TUNING_FORK@9","DEFEND_IRONCLAD",1,12)]:
            g=self.rows[name]["graphs"]["reduced"]
            self.assertIn(mechanism,g["nodes"][0]["active"])
            if name=="fork": self.assertEqual(g["nodes"][0]["state"]["tuning_fork"],9)
            n=next(n for p,n in paths(g) if p==(card,))
            self.assertEqual(n["joint"][idx],expected)
            self.assertNotIn(mechanism,n["active"])

    def test_paid_draw_and_public_policy(self):
        g=self.rows["draw"]["graphs"]["reduced"]
        h=self.rows["draw_reverse"]["graphs"]["reduced"]
        self.assertEqual(g["nodes"],h["nodes"])
        self.assertEqual(g["calls"],h["calls"])
        c=g["nodes"][g["nodes"][0]["edges"][0]["to"]]
        self.assertEqual(c["kind"],"C")
        self.assertEqual((c["state"]["paid"]["energy"],c["state"]["paid"]["remaining"]),(2,1))
        branches={e["input"]:e for e in c["edges"]}
        for card,w,label in [("STRIKE_IRONCLAD#0",1/3,"goal_expand"),("BLUDGEON#0",2/3,"ordinary_end_turn")]:
            e=branches[card]
            self.assertAlmostEqual(e["probability"],w)
            self.assertEqual(g["nodes"][e["to"]]["approximation"],label)
        plan=policy(g,lambda kind,p:float(kind=="victory"),first=0)
        self.assertAlmostEqual(plan["modeled_complete_mass"],1/3)
        tree=self.rows["draw"]["graphs"]["tree"]
        self.assertAlmostEqual(policy(tree,lambda kind,p:float(kind=="victory"),first=0)["modeled_complete_mass"],1/3)
        self.assertAlmostEqual(plan["deferred_end_turn_mass"],2/3)
        self.assertEqual(policy(g,first=g["nodes"][0]["end"])["deferred_end_turn_mass"],1)
        self.assertNotEqual(self.rows["draw"]["after"]["hand"],self.rows["draw_reverse"]["after"]["hand"])

    def test_b_and_terminal_contract(self):
        for row in self.rows.values():
            leaves=row["settlement"]["successors"]
            self.assertAlmostEqual(sum(e["probability"] for e in leaves),1)
            for leaf in leaves:
                if leaf["kind"]=="B":
                    self.assertEqual(leaf["state"]["turn"],2)
                    self.assertEqual(leaf["state"]["decision"]["phase"],"combat")
                    self.assertTrue(any(a["kind"]=="end_turn" for a in leaf["state"]["actions"]))
                    self.assertIn("belief",leaf)
        basic=self.rows["basic"]["settlement"]["successors"]
        self.assertEqual(len(basic),10)
        self.assertEqual({e["kind"] for e in basic},{"B"})
        self.assertEqual({e["state"]["hp"] for e in basic},{76})
        hands=set()
        for leaf in basic:
            self.assertAlmostEqual(leaf["probability"],0.1)
            hands.add(tuple(c["id"] for c in leaf["state"]["hand"]))
        self.assertEqual(len(hands),10)
        self.assertIn(tuple(c["id"] for c in self.rows["basic"]["after"]["hand"]),hands)
        self.assertEqual(self.rows["lethal"]["settlement"]["successors"][0]["kind"],"victory")

    def test_public_belief_fails_closed(self):
        row=self.rows["draw"]
        root=row["graphs"]["reduced"]["nodes"][0]["state"]
        self.assertEqual(belief(root,[]),{"STRIKE_IRONCLAD#0":1,"BLUDGEON#0":2})
        self.assertIsNone(belief(root|dict(draw_count=2),[]))
        self.assertIsNone(belief(root|dict(relics=["unqualified"]),[]))

    def test_implementation_identity(self):
        build=json.loads((EVIDENCE/"build.json").read_bytes())
        for name in ("Tactical.cs","PublicDraw.cs","belief_cards.json"):
            self.assertEqual(source_sha(HERE/name),build["sources"][name])

    def test_censored_branch_is_not_complete(self):
        g=self.rows["draw"]["graphs"]["reduced"]
        nodes=list(g["nodes"])
        chance=nodes[nodes[0]["edges"][0]["to"]]
        ordinary=next(e["to"] for e in chance["edges"] if e["input"]=="BLUDGEON#0")
        nodes[ordinary]=dict(kind="budget",state=None,joint=None,edges=[],end=None,active=[])
        truncated=g|dict(nodes=nodes)
        p=policy(truncated,lambda kind,joint:float(kind=="victory"),first=0)
        self.assertAlmostEqual(p["modeled_complete_mass"],1/3)
        self.assertAlmostEqual(p["unresolved_tactical_mass"],2/3)
        self.assertEqual(p["deferred_end_turn_mass"],0)
    def test_resumed_next_hand_law(self):
        rows=json.loads(gzip.decompress((EVIDENCE/"integral.json.gz").read_bytes()))["rows"]
        self.assertEqual(len(rows),4)
        for row in rows:
            self.assertLessEqual(row["requests"],128)
            self.assertGreaterEqual(row["mass128"].get("B",0),row["mass8"].get("B",0))
            self.assertAlmostEqual(sum(row["mass128"].values()),1)
            addresses=[(json.dumps(e["route"]),tuple(e["setup"])) for e in row["settlement"]["events"]]
            self.assertEqual(len(addresses),len(set(addresses)))

    def test_development_archive(self):
        with zipfile.ZipFile(EVIDENCE/"panel.zip") as z:
            panel=json.loads(z.read("panel.json"))
            details=[json.loads(gzip.decompress(z.read(r["family"]+".json.gz"))) for r in panel["rows"]]
        self.assertEqual(len(details),24)
        self.assertEqual(metrics(panel,details),json.loads((EVIDENCE/"summary.json").read_bytes()))
        for d in details:
            for turn,leaf in enumerate(d["leaves"],1):
                if leaf["kind"]=="B": self.assertTrue(is_next_decision(leaf["state"],turn))
            for q in d["queries"]:
                g=q["graph"]
                self.assertLessEqual(g["calls"],g["transition_budget"])
                p=policy(g)
                self.assertEqual(p["successors"],q["policy"]["successors"])
                exported=strategic_successors(g,p,q["settlement"])
                self.assertAlmostEqual(sum(exported["mass"].values()),1)
                for n in g["nodes"]:
                    if n["kind"]=="C":
                        self.assertAlmostEqual(sum(e["probability"] for e in n["edges"]),1)
                for s in q["settlement"]["successors"]:
                    if s["kind"]=="unresolved": self.assertTrue(s["reason"])
                    if s["kind"]=="deferred":
                        self.assertIn("setup",s)
                        self.assertNotIn("state",s)
                self.assertAlmostEqual(sum(s["probability"] for s in q["settlement"]["successors"]),1)


if __name__=="__main__":
    unittest.main()
