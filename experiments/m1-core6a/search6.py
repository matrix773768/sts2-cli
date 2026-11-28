"""CORE proposal controller over public menus and H5 complete, probability-checked programs."""
from collections import Counter
import numpy as np
from common6 import *
from policy6 import Guide
from client import Client
import hot_produce as hot

original_portfolio=hot.portfolio
LOW={"low","g2low"}
GUIDED=LOW|{"same24","same32","same48","trim32"}
class Actor(Models):
    def __init__(self,arm):
        super().__init__()
        self.arm=arm
        self.metrics=Counter()
        self.guide=None
        if arm not in {"g2","v2","g2low"}:
            info=read(E/"picked.json")
            weights=E/(info["name"]+".pt")
            assert sha(weights)==info["weight"]
            self.guide=Guide(weights)
        self.context=None

    def identity(self,arm,limit,margin=0.):
        parent=super().identity("tactical",32)
        assert parent["id"]==POLICY
        if self.arm=="v2":return parent
        if self.arm=="g2":return super().identity("g2",32)
        body=dict(schema="sts2.core6a.policy.v1",arm=self.arm,parent=parent["id"],limit=limit,
                  code={f:sha(HERE/f) for f in ("policy6.py","search6.py")},weight=read(E/"picked.json")["weight"] if self.guide else None)
        return body|dict(id=digest(body))

    def rank(self,h,history,opening):
        if self.arm=="direct":return self.learned(h,history,opening)[0]
        self.context=(h,history,opening)
        return super().rank(h,history,opening)

    def learned(self,h,history,opening):
        self.metrics["policy_menus"]+=1
        if len(h["actions"])==1:return [0],1.
        scores=self.guide.scores(h,history,opening)
        rank=np.argsort(-scores,kind="stable").tolist()
        return rank,float(scores[rank[0]]-scores[rank[1]])

class Continuation:
    def __init__(self,model):
        self.model=model
        self.g2=model.g2
        self.advance=model.advance
    def rank(self,h,history,opening):
        self.model.metrics["learned_choice" if h["decision"]["phase"]=="choice" else "learned_follow"]+=1
        return self.model.learned(h,history,opening)[0]

class SearchClient(Client):
    def __init__(self,out,record):
        super().__init__(out)
        self.record=record
        self.pending_ref=None
        self.steps=[]
        self.last=None
    def call(self,op,**fields):
        if op=="open":
            self.steps=[]
            self.pending_ref=None
        elif op=="step":
            self.steps.append(dict(index=fields["index"],observation=self.last))
        reply=super().call(op,**fields)
        if op in {"step","open"}:
            self.last={k:reply[k] for k in ("status","view","facts","kind","options") if k in reply}
        return reply
    def reference(self,index,limit,models,h,history,opening):
        if self.pending_ref is not None:
            witness,graph=self.pending_ref
            assert witness==(id(h),index,limit)
            self.pending_ref=None
            return graph
        return super().reference(index,limit,models,h,history,opening)

def portfolio(client,model,rank,opening,arm,limit):
    mode=model.arm
    if mode not in GUIDED:return original_portfolio(client,model,rank,opening,arm,limit)
    h,memory,_=model.context
    end=next(i for i in rank if h["actions"][i]["kind"]=="end_turn")
    low=mode in LOW or mode=="trim32"
    if low:
        ref=Client.reference(client,rank[0],limit,model,h,memory,opening)
        client.pending_ref=((id(h),rank[0],limit),ref)
        if ref["gaps"]:
            model.metrics["skipped_open_reference"]+=1
            return []
    if mode=="g2low":
        order,margin=rank,None
    else:
        order,margin=model.learned(h,memory,opening)
    opportunity=any((a.get("preview") or {}).get("draw") or a.get("energy_x") for a in h["actions"])
    if low:
        extra=opportunity or (margin is not None and margin<.55)
        width=(3 if mode=="trim32" else 2)+int(extra)
        ids=list(dict.fromkeys([*order[:width],rank[0],end]))
    else:ids=order
    model.metrics["legal_first_on_expansion"]+=len(rank)
    model.metrics["expanded_first"]+=len(ids)
    model.metrics["expansions"]+=1
    groups=[]
    def append(graphs,style):
        groups.extend((g,v|dict(style=style)) for g,v in zip(graphs,model.backup(graphs,opening),strict=True))
    styles=("light","guard") if mode in LOW else ("light","guard","build","end")
    for style in styles:
        # Full-budget mode exchanges one continuation at the first two priorities, keeping four programs per action.
        indices=[i for i in ids if low or style!="end" or i not in order[:2]]
        if indices:append(client.call("search",indices=indices,limit=limit,style=style),style)
    for index in order[:1 if low else 2]:
        follower=model if mode=="g2low" else Continuation(model)
        graph=Client.reference(client,index,limit,follower,h,memory,opening)
        append([graph],"g2-follow" if mode=="g2low" else "learned-follow")
    return groups

