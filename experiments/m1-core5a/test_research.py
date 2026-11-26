import unittest,json,gzip
from unittest.mock import patch
from types import SimpleNamespace
from copy import deepcopy
import numpy as np
from search5 import FIVE,reference,Evaluator,cached_row
from assessment import rows,load_value
from semantic import torch,encode,pack,expected
from core4_roots import panels

class ReferenceTests(unittest.TestCase):
    def test_branch_history_and_missing_mass(self):
        events=[]
        def update(hist,o,a):return hist+(a["kind"],)
        model=SimpleNamespace(encoder=SimpleNamespace(update=update))
        ctrl=SimpleNamespace(history=("prefix",),score=lambda requests:[(np.array(requests[0][0]["scores"]),None)])
        root=dict(actions=[dict(kind="play")],scores=[1])
        def request(_,route):
            if not route[0]["draws"]:return dict(response=dict(kind="R",support={"a":1,"b":3},calls=1))
            a=route[0]["draws"][0]=="a"
            if len(route)==1:return dict(response=dict(kind="decision",
                state=dict(scores=[int(a),int(not a)],actions=[dict(kind="pick"),dict(kind="pass")]),calls=1))
            self.assertEqual(route[-1]["action"],0 if a else 1)
            return dict(response=dict(kind="victory" if a else "unresolved",state={"hp":5},calls=2))
        lane=SimpleNamespace(request=request,host=SimpleNamespace(project=lambda h:h))
        with patch("search5.prepared",return_value=ctrl):
            leaves,_,idx=reference(lane,root,[],model,observe=lambda *v:events.append(v))
            limited,_,_=reference(lane,root,[],model,limit=1)
        self.assertEqual(idx,0)
        self.assertEqual([v[1] for v in events],[("prefix",),("prefix","play"),("prefix","play")])
        self.assertEqual({l["kind"]:l["probability"] for l in leaves},{"victory":.25,"unresolved":.75})
        self.assertEqual(sum(x["probability"] for x in limited if x["kind"]=="deferred"),1)

    def test_mechanism_and_model_cache(self):
        old=FIVE.parent/"m1-core4/evidence"
        c=next(rows(old/"on0.gz"))["states"][0]
        alias=deepcopy(c);alias["unencoded_audit_tag"]=42
        for a,b in zip(encode(c),encode(alias,row_fn=cached_row)):np.testing.assert_array_equal(a,b)
        torch.set_num_threads(1)
        v1=Evaluator(load_value(old/"v1.pt"));v0=Evaluator(load_value(old/"v0.pt"))
        opening=dict(hp=c["hp"],max_hp=c["max_hp"])
        base=v1({"x":c,"y":alias},opening)
        self.assertEqual(base["x"],base["y"]);self.assertEqual(v1.misses,1)
        changed=v1({"x":c},opening|dict(hp=c["hp"]+5))
        with torch.no_grad():
            p=v1.net(*pack([encode(c)])).softmax(-1)
            value=expected(p,torch.tensor(c["hp"]+5),torch.tensor([c["hp"]]),torch.tensor(c["max_hp"]))
        self.assertAlmostEqual(value.item(),changed["x"],places=5)
        self.assertNotEqual(base["x"],v0({"x":c},opening)["x"])
        self.assertEqual(v0.misses,1)

    def test_panel_and_evidence(self):
        evidence=FIVE/"evidence"
        with gzip.open(evidence/"panels.gz","rt") as f:p=json.load(f)
        composition=lambda j:tuple(sorted(c["id"] for c in j[1]["deck"]))
        old={composition(j) for jobs in panels().values() for j in jobs}
        fresh={composition(j) for j in p["confirm"]}
        self.assertEqual(len(fresh),96);self.assertFalse(old&fresh)
        audit=json.loads((evidence/"audit.json").read_bytes())
        self.assertFalse(audit["differences"])
        for k in ("choice_decisions","observed_draws","C","death","victory"):self.assertGreater(audit["counts"][k],0)
        results=json.loads((evidence/"benchmark.json").read_bytes())
        self.assertTrue(all(x["matches"]==52 for x in results["runs"]))
        result=json.loads((evidence/"results.json").read_bytes())
        self.assertEqual(result["train_pairs"]["counts"]["distinct_C"],json.loads((evidence/"fit.json").read_bytes())["paired_labels"])
        for a in ("original","v1","v2"):
            for file in evidence.glob(f"confirm-{a}-*.gz"):
                for r in rows(file):
                    for q in r["queries"]:
                        if q["used"]:
                            self.assertGreaterEqual(min(q["coverage"],q["reference_coverage"]),1-1e-9)
                            self.assertGreater(q["value"]-q["reference"],1)
