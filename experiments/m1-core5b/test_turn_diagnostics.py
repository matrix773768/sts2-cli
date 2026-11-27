import unittest,json,gzip
from collections import defaultdict
from turn_summary import read_cases
from turn_probe import E,source
from turn_lines import HEAD,TRANCE,IMP

class DiagnosticTests(unittest.TestCase):
    def test_assignment_and_terminal_pairing(self):
        for tag in ("rescue","loss"):
            worlds=defaultdict(dict)
            for r in read_cases(tag):
                self.assertNotIn(r["name"],worlds[r["world"]]);worlds[r["world"]][r["name"]]=r
                self.assertIn(r["status"],("death","predicted_win"));self.assertIsNotNone(r["terminal"])
            self.assertEqual(len(worlds),49)
            for arms in worlds.values():
                self.assertEqual(len(arms),6)
                # Every draw-first arm observes exactly the same cards in this world.
                names=("defend2","shrug_bash","adaptive_v1","adaptive_v2") if tag=="rescue" else ("trance_static","adaptive_v1","adaptive_v2")
                self.assertEqual(len({arms[n]["actions"][1]["hand"] for n in names}),1)
            self.assertEqual(worlds[None]["deployed"]["terminal"]["hp"],source(tag)["right"]["row"]["terminal"]["hp"])

    def test_public_laws_and_placement(self):
        for tag,count in (("loss",60),("rescue",11)):
            d=json.load(gzip.open(E/f"turn-probe-{tag}.gz"));self.assertEqual(len(d["reveal"]),count)
            self.assertAlmostEqual(sum(x["p"] for x in d["reveal"].values()),1)
            for name,line in d["lines"].items():
                self.assertAlmostEqual(line["coverage"],1)
                for i in (0,1):
                    self.assertAlmostEqual(line["v"][i],sum(p*d["values"][k][i] for k,p in line["dist"].items()))
            for z in d["reveal"].values():
                for i in (0,1):
                    best=next(o for o in z["options"] if o["seq"]==z["best"][i])
                    self.assertAlmostEqual(best["coverage"],1)
                    self.assertEqual(best["v"][i],max(o["v"][i] for o in z["options"] if o["coverage"]>1-1e-9))
            if tag=="loss":
                w=d["lines"]["head_combo"]["witness"];self.assertEqual(len(w),20)
                for r in w:
                    acts=r["actions"]
                    self.assertEqual([tuple(a) for a,t in acts],[HEAD,("pick","IMPERVIOUS",1),("confirm_selection",),TRANCE,IMP,("end_turn",)])
                    self.assertEqual(acts[3][1][0],"IMPERVIOUS#1");self.assertAlmostEqual(r["p"],.05)

    def test_specific_frontier_stops(self):
        graph=json.loads((E/"turn-graph-loss.json").read_bytes())["rows"]["high"]["policies"]
        self.assertAlmostEqual(graph["head_combo"]["blocked"]["unsupported_pending_choice"],1)
        self.assertAlmostEqual(graph["adaptive_v2"]["blocked"]["draw_depth_cap"],1)
        filt=json.load(gzip.open(E/"turn-filter.gz"))["rows"]
        self.assertEqual(filt["after_choice"]["law"]["top"],["IMPERVIOUS#1"])
        self.assertAlmostEqual(filt["after_trance"]["arms"]["third=False/high"]["policies"]["after_trance"]["mass"]["settled"],1)
        expanded=filt["root"]["arms"]["third=True/high"]["reveals"]
        self.assertAlmostEqual(sum(z["p"] for z in expanded if z.get("approx")=="goal_expand"),1)
        for tag in ("loss","rescue"):
            for r in json.loads((E/f"turn-native-{tag}.json").read_bytes())["rows"].values():
                self.assertTrue(r["matches"],r)
if __name__=="__main__":unittest.main()
