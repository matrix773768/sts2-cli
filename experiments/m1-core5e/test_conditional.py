import json,unittest
import torch
from panel5e import D,E,FIVE,HERE,load,rows,digest
from targets5e import deposit,terminal_target,temporal_target,CENTERS
from data5e import read_cases,completed
from value import expected

class ConditionalLearning(unittest.TestCase):
    def test_signed_interpolation_and_death(self):
        hp=torch.tensor([50,50,50]);end=torch.tensor([27,73,0])
        p=terminal_target(hp,end,torch.tensor([False,False,True]))
        centers=p.new_tensor(CENTERS)
        torch.testing.assert_close(p[:,1:]@centers,torch.tensor([23.,-23.,0.]))
        torch.testing.assert_close(p.sum(1),torch.ones(3))
        self.assertEqual(float(p[2,0]),1.)
        self.assertAlmostEqual(float(p[0,1+CENTERS.index(25)]),.6,places=5)
    def test_shift_with_mixed_death_and_heal(self):
        p=torch.zeros(2,len(CENTERS)+1);p[:,0]=.25;p[:,1+CENTERS.index(20)]=.75
        hp=torch.tensor([40,40]);nxt=torch.tensor([36,49])
        q,tail=temporal_target(p,hp,nxt)
        torch.testing.assert_close(p[:,0],q[:,0]);torch.testing.assert_close(q.sum(1),torch.ones(2))
        torch.testing.assert_close(q[:,1:]@q.new_tensor(CENTERS),torch.tensor([24.,11.])*.75)
        opening=torch.tensor([50,50]);mx=torch.tensor([80,80])
        torch.testing.assert_close(expected(q,opening,hp,mx),expected(p,opening,nxt,mx))
        self.assertFalse(tail.any())
    def test_shift_tail_is_accounted(self):
        p=torch.zeros(1,len(CENTERS)+1);p[0,-1]=.2;p[0,0]=.8
        q,overflow=temporal_target(p,torch.tensor([3]),torch.tensor([1]))
        torch.testing.assert_close(p,q);self.assertAlmostEqual(float(overflow[0]),.2)
    def test_actual_adjacency(self):
        edges=ends=0
        for pattern in ("train-V2-*","train2-V2-*"):
            for f in D.glob(pattern+".gz"):
                for r in rows(f):
                    if not r["terminal"]:continue
                    cs=r["states"]
                    for a,b in zip(cs,cs[1:]):self.assertEqual(a["turn"]+1,b["turn"]);edges+=1
                    if cs:self.assertEqual(cs[-1]["turn"],r["terminal"]["turn"]);ends+=1
        self.assertEqual((edges,ends),(1916,510))
    def test_independent_panel(self):
        panel=load(E/"panel.gz");fresh=panel["confirm"]
        self.assertEqual(len({w["family"] for w in fresh}),64)
        self.assertEqual(len({(w["family"],w["spec"]["seed"]) for w in fresh}),128)
        comp=lambda w:digest(sorted(c["id"] for c in w["spec"]["deck"]))
        old=load(D/"panel.gz")
        self.assertFalse({comp(w) for w in fresh}&{comp(w) for v in old.values() for w in v})
    def test_world_integrity(self):
        for split in ("train","dev"):
            for r in read_cases(split):
                if not completed(r):continue
                self.assertEqual(r["continuation"],"5C-V2-high")
                self.assertEqual(len({w["seed"] for w in r["worlds"]}),r["world_count"])
                self.assertTrue(all(abs(sum(z[3] for z in opt["law"])-1)<1e-8 for opt in r["plans"]))
                for w in r["worlds"]:
                    for o,plan in zip(w["outcomes"],r["plans"]):
                        if o["realized"]:
                            self.assertTrue(any(k=="C" and key==o["realized"] for k,key,_,_ in plan["law"]))

    def test_previous_policy_switch_is_separate_from_g2(self):
        from unittest.mock import patch
        from options5d import Option
        from incumbent5e import IncumbentPlanner
        def opt(label,key):
            return Option(label,label,0,[("C",key,0.,1.)],lambda lane,st:(st,[],label))
        before=opt("graph/0","b");fallback=opt("G2","g")
        planner=IncumbentPlanner(None,None,None)
        for delta,switch,use in ((.75,False,True),(2.,True,False)):
            planner.evaluate=lambda states,spec:{"b":1.,"g":1.+delta}
            with patch("incumbent5e.menu",return_value=([before,fallback],{},"graph/0",{"use":True})):
                _,_,q=planner(None,None,[],None,None,{})
            self.assertEqual((q["generation_switch"],q["use"]),(switch,use))
        with patch("incumbent5e.menu",return_value=([],{},"G2",{"use":False})):
            _,_,q=planner(None,None,[],None,None,{})
            self.assertFalse(q["incumbent_available"] or q["generation_switch"] or q["use"])
if __name__=="__main__":unittest.main()
