import unittest,gzip,json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from deploy5b import E,FIVE,BUDGET,ROOT,init,reference,records,Lane
from play_loop import cohort

class CapabilityTests(unittest.TestCase):
    def test_cold_and_cached_laws(self):
        panel=json.load(gzip.open(E/"panel.gz"))
        class Cold:
            def __init__(self,lane):self.host=lane.host;self.lane=lane
            def request(self,key,**args):
                self.lane.request("i1_core5_reference",clear=True)
                return self.lane.request(key,**args)
        with TemporaryDirectory(dir=ROOT/"logs") as temp:
            host,g2,_,_=init(Path(temp),"base");lane=Lane(host,0)
            try:
                for w in panel["historical"][8:20:3]:
                    s=cohort.start(lane,w["spec"]);h=host.project(s["observation"])
                    warm,n,a=reference(lane,h,[],g2);cold,m,b=reference(Cold(lane),h,[],g2)
                    strip=lambda v:[{k:y for k,y in x.items() if k!="calls"} for x in v]
                    self.assertEqual(strip(warm),strip(cold));self.assertEqual(a,b)
                    self.assertLessEqual(n,m);self.assertAlmostEqual(sum(x["probability"] for x in warm),1.)
                    lane.request("i1_core5_reference",clear=True);lane.reset()
            finally:lane.close();host.close()

    def test_panels_and_weights(self):
        p=json.load(gzip.open(E/"panel.gz"));old=json.load(gzip.open(FIVE/"evidence/panels.gz"))
        comp=lambda spec:tuple(sorted(c["id"] for c in spec["deck"]))
        fresh={comp(w["spec"]) for w in p["fresh"]}
        self.assertEqual(len(fresh),48)
        self.assertFalse(fresh&{comp(j[1]) for jobs in old.values() for j in jobs})
        self.assertEqual(set(Counter(w["family"] for w in p["fresh"]).values()),{2})
        self.assertEqual(len({w["family"] for w in p["oracle"]}),40)
        self.assertEqual(len({w["family"] for w in p["high"]}),48)
        self.assertEqual(p["high"][:24],p["oracle"][:24]);self.assertEqual(BUDGET["high"],BUDGET["V1high"])
        self.assertEqual(BUDGET["base"][:2],BUDGET["ref768"][:2])

    def test_gate_and_mass(self):
        for group in ("historical","fresh","high"):
            for f in E.glob(group+"-*.gz"):
                for r in records(f):
                    for q in r["queries"]:
                        self.assertAlmostEqual(sum(q["candidate_mass"].values()),1.)
                        self.assertAlmostEqual(sum(q["reference_mass"].values()),1.)
                        self.assertEqual(q["used"],min(q["reference_coverage"],q["coverage"])>=1-1e-9 and q["value"]>q["reference"]+1)
                        if q["used"]:self.assertIn(q["result"],("end","terminal"))

    def test_native_wins(self):
        oracles=list(records(E/"oracle.gz"))
        witnesses=[(r["world"],r["reference"]) for r in oracles if r["reference"]]
        for f in E.glob("beam-*.gz"):
            witnesses.extend((r["world"],r["validation"]) for r in records(f) if r.get("validation",{}).get("status")=="native_win")
        self.assertEqual(len({w["family"] for w,v in witnesses}),4)
        for w,v in witnesses:
            self.assertEqual(v["length"],len(v["frame_hashes"]))
            self.assertEqual(v["end_hp"],v["terminal"]["outcome"]["final_hp"])
            self.assertEqual(v["net"],w["spec"]["hp"]-v["end_hp"]);self.assertGreater(v["end_hp"],0)
        transfers=json.loads((E/"hp-native.json").read_bytes())["rows"]
        self.assertTrue(all(r["locked"] and r["decision"]=="card_reward" and r["status"]=="native_win" for r in transfers))
        self.assertEqual(len({r["family"] for r in transfers}|{w["family"] for w,v in witnesses}),5)

    def test_audit_and_causal_replay(self):
        audit=json.loads((E/"audit.json").read_bytes());self.assertFalse(audit["differences"])
        for k in ("event_hand","event_draw","event_target","event_enemy","decision","C","death","victory"):
            self.assertGreater(audit["counts"][k],0)
        transfer=json.loads((E/"hp-replay.json").read_bytes())["rows"]
        self.assertTrue(all(x["same_hand"] and x["same_enemies"] for x in transfer))
        for tag,outcome,alt in (("rescue","predicted_win","death"),("loss","death","predicted_win"),("fifth","predicted_win","death")):
            d=json.load(gzip.open(E/f"review-{tag}.gz"));right=d["right"]
            self.assertEqual(d["left"]["snapshot"]["h"],right["snapshot"]["h"])
            self.assertEqual(right["row"]["status"],outcome);self.assertEqual(d["alternates"]["reference"]["row"]["status"],alt)
        a=json.loads((E/"candidate-audit.json").read_bytes())["rows"]
        self.assertAlmostEqual(a["base"]["mass"]["represented"],1)
        self.assertLess(a["base"]["mass"]["admitted"],1);self.assertAlmostEqual(a["high"]["mass"]["resolved"],1)

if __name__=="__main__":unittest.main()
