"""Protocol and packed-evidence regressions, including negative and censoring cases."""
import gzip
import itertools
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

from fit import example
from cohort import HERE, digest, permutation, seed
import torch


class EmptyEncoder:
    def initial_history(self):
        return ()

    def encode(self,h,mem):
        return {"hp":h["hp"]}


class Protocol(unittest.TestCase):
    def test_permutation(self):
        deck=[dict(id=x,upgrade=0) for x in "AABCDXYZ"]
        hand=[deck[i] for i in (5,0,1,3,4)]
        x=permutation(deck,hand,"1")
        self.assertEqual(sorted(x),list(range(len(deck))))
        self.assertEqual([deck[i] for i in x[:5]],hand)
        self.assertEqual(permutation(deck,hand,"1"),x)
        self.assertGreater(len({tuple(permutation(deck,hand,str(i))) for i in range(12)}),1)
        with self.assertRaises(StopIteration):
            permutation(deck,hand+[dict(id="MISSING",upgrade=0)],"1")

    def test_v_is_greedy_and_q_is_distributed(self):
        win=dict(status="predicted_win",terminal=dict(hp=55))
        loss=dict(status="death",terminal=dict(hp=0))
        world=lambda a,b:dict(outcomes={"1":a,"3":b})
        r=dict(h=dict(hp=50),history=[],options=[1,3],
               blocks=dict(paired=[world(win,loss),world(win,win)],extra=[world(loss,None),world(loss,None)]))
        ordinary=example(r,EmptyEncoder(),0,False)
        cf=example(r,EmptyEncoder(),0,True)
        torch.testing.assert_close(ordinary[1],cf[1])
        self.assertEqual(float(cf[1][0]),0)
        self.assertEqual(ordinary[2],[1])
        self.assertEqual(float(ordinary[3][0,0]),.5)
        self.assertEqual(cf[2],[1,3])
        self.assertEqual(float(cf[3][1,0]),.5)
        torch.testing.assert_close(cf[3].sum(-1),torch.ones(2))

    def test_ledger_isolation_and_uniform_world_design(self):
        ids=set()
        families=set()
        keys=set()
        with ZipFile(HERE/"evidence/raw.zip") as archive:
            for split in ("train","dev","confirm"):
                directory="n4-v2-"+split+"/"
                jobs=json.loads(archive.read(directory+"manifest.json"))["jobs"]
                for ordinal,spec,s,family,_ in jobs:
                    self.assertEqual(s,split)
                    self.assertNotIn(family,families)
                    families.add(family)
                    key=tuple(sorted(c["id"] for c in spec["deck"]))
                    self.assertNotIn(key,keys)
                    keys.add(key)
                    r=json.loads(gzip.decompress(archive.read(directory+f"{ordinal:03}.json.gz")))
                    self.assertEqual((r["ordinal"],r["family"],r["split"]),(ordinal,family,s))
                    if r.get("h"):
                        self.assertEqual(r["key"],digest([r["history"],r["h"]]))
                        self.assertTrue(set(("order","seed","terminal","rng")).isdisjoint(r["h"]))
                    for block,worlds in r["blocks"].items():
                        for w in worlds:
                            self.assertEqual(w["seed"],seed(family,"main"+block,w["proposal"]))
                            self.assertNotIn(w["seed"],ids)
                            ids.add(w["seed"])
                            self.assertEqual(sorted(w["order"]),list(range(len(spec["deck"]))))
                            opts=r["options"][:1] if block=="extra" else r["options"]
                            self.assertEqual(list(w["outcomes"]),list(map(str,opts)))
                            self.assertTrue(all(y["actions"][0]==int(a) for a,y in w["outcomes"].items()))
                    if r["stop"]=="complete":
                        for b,ws in r["blocks"].items():
                            self.assertEqual(len(ws),r["k"]*(len(r["options"])-1 if b=="extra" else 1))
                    elif r["stop"]=="proposal_cap":
                        self.assertTrue(any(len(ws)<r["k"]*(len(r["options"])-1 if b=="extra" else 1)
                                            for b,ws in r["blocks"].items()))
            self.assertEqual(len(families),156)

    def test_native_qualification_and_exclusions(self):
        with ZipFile(HERE/"evidence/raw.zip") as z:
            a=json.loads(z.read("n4-v2-qualify/qualification.json"))
            for _,group in itertools.groupby(a["audits"],key=lambda v:v["id"]):
                worlds=list(group)
                self.assertEqual(len({w["history"] for w in worlds}),1)
                for key in ("pile","rng"):
                    self.assertEqual(len({w[key] for w in worlds}),2)
                self.assertTrue(all(w["order_verified"] and w["native"]["terminal_match"] for w in worlds))
            self.assertIn("predicted 1..1, native 0..1",a["known_demon"]["issue"])
            audits=json.loads(z.read("n4-v2-endcheck/terminal.json"))["routes"]
            self.assertTrue(all(v["check"].get("terminal_verified") or v["check"].get("strict",{}).get("terminal_match")
                                for v in audits.values()))
