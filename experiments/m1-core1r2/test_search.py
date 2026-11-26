import gzip
import json
import os
import unittest
import zipfile
from pathlib import Path

from build import sha,source_sha
from measure import load,metrics
from search import frontier_witnesses,integrate,mass_kind,policy,rule_context,strategic_successors

HERE=Path(__file__).resolve().parent
EVIDENCE=Path(os.environ.get("CORE1R2_EVIDENCE",HERE/"evidence"))


class Evidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=load(EVIDENCE/"fixtures.json.gz")["rows"]

    def test_frontiers_and_legal_witnesses(self):
        self.assertEqual(len(self.rows),16)
        for name,row in self.rows.items():
            with self.subTest(name=name):
                tree,red=(row["graphs"][k] for k in ("tree","reduced"))
                self.assertFalse(set(tree["counts"]) & {"budget","depth_cap","draw_depth_cap"})
                self.assertEqual(set(map(tuple,tree["no_draw_front"])),{tuple(w["joint"]) for w in frontier_witnesses(red)})
                self.assertLess(red["calls"],tree["calls"])
                for witness in frontier_witnesses(red):
                    node=red["nodes"][0]
                    for step in witness["route"]:
                        edge=next(e for e in node["edges"] if e["input"]["index"]==step["action"])
                        self.assertEqual(node["state"]["actions"][step["action"]]["kind"],"play_card")
                        node=red["nodes"][edge["to"]]
                    self.assertEqual(node["state"]["actions"][witness["end"]]["kind"],"end_turn")
                    self.assertEqual(node["joint"],witness["joint"])

    def test_classification_dominance_and_scoped_thresholds(self):
        graphs=self.rows["upgrade"]["graphs"]
        self.assertEqual([graphs[k]["calls"] for k in ("tree","no_dominance","reduced")],[85,18,8])
        for name,role,proc,axis,expected in [("nunchaku","attack",1,2,3),("fork","block",2,1,12)]:
            graph=self.rows[name]["graphs"]["reduced"]
            root=graph["nodes"][0]
            self.assertTrue(all(e["threshold"]==(proc if e["role"]==role else 0) for e in root["effects"]))
            action=next(e["index"] for e in root["effects"] if e["role"]==role)
            edge=next(e for e in root["edges"] if e["input"]["index"]==action)
            after=graph["nodes"][edge["to"]]
            self.assertEqual(after["joint"][axis],expected)
            self.assertTrue(all(e["threshold"]==0 for e in after["effects"]))
        mixed=self.rows["mixed"]["graphs"]["reduced"]["nodes"][0]
        self.assertEqual(next(e["role"] for e in mixed["effects"] if e["card"]=="IRON_WAVE"),"mixed")

    def test_precedence_and_local_order_search(self):
        def routes(graph,idx=0,route=()):
            yield route
            for edge in graph["nodes"][idx]["edges"]:
                menu=edge["input"]
                if not isinstance(menu,dict): continue
                card=graph["nodes"][idx]["state"]["hand"][menu["card"]]["id"]
                yield from routes(graph,edge["to"],(*route,card))
        for name,buff,benefit in [("strength","INFLAME","STRIKE_IRONCLAD"),
                                  ("dexterity","FOOTWORK","DEFEND_SILENT"),("vulnerable","BASH","STRIKE_IRONCLAD")]:
            paths=set(routes(self.rows[name]["graphs"]["reduced"]))
            self.assertTrue({(buff,),(benefit,),(buff,benefit)}<=paths)
            self.assertFalse(any(buff in p and benefit in p and p.index(benefit)<p.index(buff) for p in paths))
        paths=set(routes(self.rows["hp_energy_x"]["graphs"]["reduced"]))
        self.assertTrue({("BLOODLETTING","WHIRLWIND"),("WHIRLWIND","BLOODLETTING")}<=paths)

    def test_paid_draw_and_ordinary_continuation(self):
        g=self.rows["draw"]["graphs"]["reduced"]
        self.assertEqual(g["nodes"],self.rows["draw_reverse"]["graphs"]["reduced"]["nodes"])
        self.assertNotEqual(self.rows["draw"]["after"]["hand"],self.rows["draw_reverse"]["after"]["hand"])
        node=next(n for n in g["nodes"] if n["kind"]=="R")
        self.assertEqual(node["state"]["paid"]["energy"],2)
        plan=policy(g,first=0)
        by_kind={p["kind"]:p for p in plan["successors"]}
        self.assertAlmostEqual(by_kind["victory"]["probability"],1/3)
        self.assertAlmostEqual(by_kind["A"]["probability"],2/3)
        self.assertEqual(by_kind["A"]["joint"][1:3],[10,0])
        ordinary=next(e for e in node["edges"] if e["input"]=="BLUDGEON#0")
        self.assertEqual(g["nodes"][ordinary["to"]]["approximation"],"ordinary_combinations")
        nodes=list(g["nodes"])
        nodes[ordinary["to"]]=dict(kind="budget",state=None,joint=None,edges=[],end=None,active=[])
        self.assertAlmostEqual(policy(g|dict(nodes=nodes),first=0)["unresolved_tactical_mass"],2/3)

    def test_incremental_zone_events(self):
        fx=self.rows["draw"]["pile_fixture"]
        op={item["operation"]:item for item in fx["observations"]}
        self.assertNotIn("POMMEL_STRIKE#0",op["bottom"]["support"])
        self.assertEqual(op["top"]["support"],{"DEFEND_IRONCLAD#0":1})
        self.assertEqual(op["draw"]["support"],op["bottom"]["support"])
        self.assertEqual(op["fixed_generation"]["belief"]["bottom"][-1],"WOUND#0")
        self.assertEqual(op["shuffle"]["support"],op["shuffle"]["belief"]["counts"])
        self.assertIsNone(op["order_gap"].get("support"))
        self.assertEqual(op["order_gap"]["belief"]["order_gap"],"random_insertion_into_ordered_pile")
        self.assertEqual(op["recovered_order"]["support"],op["order_gap"]["belief"]["counts"])
        row=self.rows["headbutt"]
        self.assertEqual(row["transcript"][-1]["law"]["top"],["STRIKE_IRONCLAD#0"])
        node=next(n for n in row["follow"]["nodes"] if n["kind"]=="R")
        self.assertEqual(node["state"]["bag"],{"STRIKE_IRONCLAD#0":1})
        obs=self.rows["exhaust_generate"]["transcript"][-1]["observation"]
        self.assertEqual([c["id"] for c in obs["exhaust"]],["POMMEL_STRIKE"])
        self.assertEqual(sum(c["id"]=="ANGER" for c in obs["discard"]),2)

    def test_c_b_and_terminal_are_separate(self):
        row=self.rows["basic"]
        outcome=row["settlement"]["successors"]
        self.assertEqual([(l["kind"],l["probability"]) for l in outcome],[("C",1.)])
        c=outcome[0]["state"]
        self.assertEqual(c,row["observed_c"])
        self.assertEqual((c["hp"],len(c["hand"]),c["setup"]["draw"]),(76,0,5))
        self.assertIn("enemy_side",c["setup"]["completed"])
        self.assertIn("hand_draw",c["setup"]["pending"])
        b=row["optional_b"]["successors"]
        self.assertEqual(len(b),10)
        self.assertTrue(all(l["kind"]=="B" and abs(l["probability"]-.1)<1e-9 for l in b))
        self.assertIn("STRIKE_IRONCLAD",rule_context(c)["cards"])
        self.assertTrue(rule_context(c)["graphs"][c["enemies"][0]["species"]])
        self.assertEqual(self.rows["lethal"]["settlement"]["successors"][0]["kind"],"victory")
        self.assertEqual(self.rows["death"]["settlement"]["successors"][0]["kind"],"death")

    def test_proxy_cannot_authorize_terminal_or_chance(self):
        class Lane:
            def request(self,cmd,mode,**args):
                if mode=="settle_c": return dict(kind="unresolved",reason="enemy_condition_unidentified",calls=1)
                return dict(kind=self.unverified,calls=1)
        lane=Lane()
        plan=dict(successors=[dict(kind="A",route=[],probability=1)])
        for lane.unverified in ("victory","death","R"):
            result=integrate(lane,{},[],plan,model_enemy=True)
            self.assertEqual(result["calls"],2)
            self.assertEqual(mass_kind(result["successors"][0]),"mechanism:enemy_condition_unidentified")

    def test_sources(self):
        identity=load(EVIDENCE/"build.json")["sources"]
        for f in HERE.glob("*.cs"): self.assertEqual(identity[f.name],source_sha(f))
        self.assertEqual(identity["n1bc_catalog"],sha(HERE.parent/"m1-n1bc/catalog.json.gz"))

    def test_panel_and_strict_replay(self):
        with zipfile.ZipFile(EVIDENCE/"panel.zip") as z:
            panel=json.loads(z.read("panel.json"))
            raw=[json.loads(gzip.decompress(z.read(r["family"]+".json.gz"))) for r in panel["rows"]]
        self.assertEqual(json.loads(json.dumps(metrics(panel,raw))),load(EVIDENCE/"summary.json"))
        self.assertEqual(len(raw),24)
        strict={(r["family"],r["position"]):r for r in load(EVIDENCE/"strict.json.gz")["rows"]}
        for row,d in zip(panel["rows"],raw):
            for q in d["queries"]:
                g=q["graph"]
                self.assertLessEqual(g["calls"],g["transition_budget"])
                exported=strategic_successors(g,q["policy"],q["settlement"],d["history"][:q["position"]])
                self.assertAlmostEqual(sum(exported["mass"].values()),1)
                audit=strict.pop((row["family"],q["position"]))
                self.assertAlmostEqual(sum(audit["mass"].values()),1)
                self.assertAlmostEqual(audit["mass"].get("C",0),exported["mass"].get("C",0))
                for n in g["nodes"]:
                    if n["kind"]=="R": self.assertAlmostEqual(sum(e["probability"] for e in n["edges"]),1)
                for leaf in exported["successors"]:
                    if leaf["kind"]=="C":
                        self.assertEqual(leaf["state"]["setup"]["stage"],"before_initial_draw")
                        self.assertNotIn("draw_pile",leaf["state"])
                        self.assertEqual(bool(leaf["state"]["enemy_models"]),bool(leaf["approximate"]))
        self.assertFalse(strict)
        contexts=[rule_context(q["observed_c"]) for d in raw for q in d["queries"] if q.get("observed_c")]
        for group in ("cards","graphs"):
            self.assertTrue(all(v is not None for ctx in contexts for v in ctx[group].values()))


if __name__=="__main__":
    unittest.main()
