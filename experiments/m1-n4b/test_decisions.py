import unittest
import numpy as np
from design import LOGS,cohort,digest,jobs,read,world
from learn_menu import Encoder,network
from teacher import assess


class Tests(unittest.TestCase):
    def test_split_and_slot_prior(self):
        js=jobs()
        self.assertEqual(len(js),112)
        self.assertEqual(len({j["family"] for j in js}),112)
        self.assertFalse({j["family"] for j in js}&{j[3] for j in cohort.plan()})
        keys=[tuple(sorted(c["id"] for c in j["spec"]["deck"])) for j in js]
        self.assertEqual(len(set(keys)),len(keys))
        for j in js:
            w=world(j,"selection",0)
            other=world(j,"reference",0)
            self.assertNotEqual(w["seed"],other["seed"])
            self.assertEqual(w["order"][:10],list(range(10)))
            self.assertEqual(sorted(w["order"]),list(range(len(j["spec"]["deck"]))))

    def test_counter_isolated_before_reveal(self):
        r=read(LOGS/"n4b-finalcore-0/000-0.json.gz")
        alt=read(LOGS/"n4b-finalcore-0/000-9.json.gz")
        self.assertEqual({k:v for k,v in r["h"].items() if k!="nunchaku"},{k:v for k,v in alt["h"].items() if k!="nunchaku"})
        _,meta,_=network(1)
        for visible in (False,True):
            e=Encoder(meta["vocabulary"],visible)
            x,y=[e.encode(row["h"],e.initial_history()) for row in (r,alt)]
            self.assertEqual(np.array_equal(x["instances"],y["instances"]),not visible)
            self.assertEqual(np.array_equal(x["player"],y["player"]),not visible)

    def test_selection_does_not_consult_reference(self):
        r=read(LOGS/"n4b-finalcore-0/000-0.json.gz")
        original=assess([r],0)["rows"]
        for w in r["worlds"]["reference"]:
            for y in w["results"]["0"]["outcomes"].values():
                y["utility"]=-y["utility"]
        changed=assess([r],0)["rows"]
        self.assertEqual([x["chosen"] for x in original],[x["chosen"] for x in changed])
        self.assertEqual([x["gain"] for x in original],[-x["gain"] for x in changed])

    def test_paths_and_terminal_contract(self):
        for p in sorted((LOGS/"n4b-finalcore-80").glob("*.gz")):
            r=read(p)
            if r["stop"]!="complete":
                continue
            for name,end in zip(("plan_atk","plan_def"),r["endpoints"]):
                self.assertIn(end["kind"],("end_play_a","victory"))
                self.assertEqual(r["paths"][name],end["steps"])
            for block in r["worlds"].values():
                for w in block:
                    for rec in w["results"].values():
                        for name,key in rec["refs"].items():
                            path=r["paths"][name]
                            self.assertEqual(digest(path),key)
                            y=rec["outcomes"][key]
                            self.assertEqual(y["trace"][:len(path)],[s[1] for s in path])
                            self.assertIn(y["status"],("death","predicted_win"))
