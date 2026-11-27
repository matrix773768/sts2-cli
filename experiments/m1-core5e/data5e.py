"""Replay-free training data for one frozen continuation, with whole-root conditional means."""
from collections import Counter
from statistics import mean
from panel5e import E,D,rows
from fit5d import Sample,logits,torch
from results5d import eligible
from targets5e import terminal_target,temporal_target
from turn_worlds import model_key

def completed(case):
    worlds=case["worlds"]
    return len(worlds)==case.get("world_count",-1) and all(len(w["outcomes"])==2 and eligible(w) for w in worlds)

def read_cases(split):
    return [case for f in sorted(E.glob(f"worlds-{split}-*.gz")) for case in rows(f)]

def deltas(case):
    return [a["utility"]-b["utility"] for a,b in (w["outcomes"] for w in case["worlds"])]

class Corpus(Sample):
    def __init__(self,split,base):
        super().__init__()
        self.natural=[];self.extra=[];self.cases=[];self.overflow=[]
        for source in (split,split+"2"):
            for path in sorted(D.glob(source+"-V2-*.gz")):
                for r in rows(path):self.trajectory(r)
            for path in sorted(D.glob("pairs-"+source+"-*.gz")):
                for case in rows(path):
                    if eligible(case):
                        assert case["continuation"]=="5C-V2-high"
                        for k,c in case["states"].items():self.add(k,c)
                        self.add_outcomes(case["outcomes"])
        for case in read_cases(split):
            if not completed(case):continue
            assert case["continuation"]=="5C-V2-high"
            self.cases.append(case)
            for key,c in case["states"].items():self.add(key,c)
            laws=[p["law"] for p in case["plans"]]
            if any(abs(sum(z[3] for z in law)-1)>1e-8 for law in laws):raise ValueError("Incomplete candidate")
            self.pairs.append((laws,case["hp"],case["max_hp"],mean(deltas(case))))
            for w in case["worlds"]:self.add_outcomes(w["outcomes"])
        self.prepare(base)

    def trajectory(self,r):
        if r["terminal"] is None:return
        if r["arm"]!="V2":raise ValueError("Unexpected continuation")
        cs=r["states"];terminal=r["terminal"]
        for i,c in enumerate(cs):
            key=(r["family"],r["seed"],c["turn"])
            self.add(key,c)
            if i+1<len(cs):
                if cs[i+1]["turn"]!=c["turn"]+1:raise ValueError("Nonadjacent natural Cs")
                successor=(r["family"],r["seed"],cs[i+1]["turn"])
            else:
                if terminal["turn"]!=c["turn"]:raise ValueError("Unobserved transition before terminal")
                successor=None
            self.natural.append((key,successor,terminal["hp"],r["status"]=="death"))

    def add_outcomes(self,outcomes):
        for o in outcomes:
            if o["realized"] is not None:self.extra.append((o["realized"],o["terminal_hp"],o["status"]=="death"))

    @torch.no_grad()
    def prepare(self,base):
        self.keys=[r[0] for r in self.natural]+[r[0] for r in self.extra]
        real=[(k,h,d) for k,_,h,d in self.natural]+self.extra
        hp=torch.tensor([self.states[k][1] for k,e,d in real])
        self.mc=terminal_target(hp,torch.tensor([e for k,e,d in real]),torch.tensor([d for k,e,d in real]))
        self.td=self.mc.clone()
        edges=[(i,b) for i,(_,b,_,_) in enumerate(self.natural) if b is not None]
        for j in range(0,len(edges),64):
            batch=edges[j:j+64];idx,k=zip(*batch)
            target,tail=temporal_target(logits(base,self,k).softmax(-1),hp[list(idx)],torch.tensor([self.states[b][1] for b in k]))
            self.td[list(idx)]=target;self.overflow.extend(tail.tolist())
        self.counts.update(natural=len(self.natural),edges=len(edges),terminal_edges=len(self.natural)-len(edges),
                           actual_branch_C=len(self.extra),conditional_roots=len(self.cases),
                           conditional_worlds=sum(len(c["worlds"]) for c in self.cases))
