"""Matched Hot checkpoints for preregistered public roots, with strict H5 qualification."""
import gzip
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
os.environ["HOTSEARCH_BUILD"]=str(ROOT/"logs/hotsearch-h5")
from client import Client
from condition import key
from models import Models,public_b,choice_b,strategic,return_law,boundary_key,torch,payoff
from hot_produce import fight,record_boundary,peak_rss
sys.modules.pop("experience", None)
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from experience import digest,require,qualify,probability
from publish_views import public
from verify2a_common import check_segment

POLICY="25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"
BEHAVIOR="51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616"
FAIL=(KeyError,IndexError,ValueError,TimeoutError,RuntimeError)
def blank():
    return dict(states=[],queries=[],trace=[],choices=[],actual_steps=0)

class Recorder:
    def __init__(self,host):
        self.host=host
    def call(self,op,**kw):
        if op=="step":
            self.steps.append(dict(index=kw["index"],observation=public(self.state)))
        ans=self.host.call(op,**kw)
        if op in ("step","open","restore"):self.state=ans
        if op in ("open","restore"):self.steps=[]
        return ans
    def reference(self,*args):
        return self.host.reference(*args)

def recover(host,m,r,case):
    st=host.call("open",spec=r["spec"])
    history=m.g2.encoder.initial_history()
    prefix=case["prefix"]
    for x in r["prefix"]["steps"]:
        require(public(st)==x["observation"] and list(st["facts"]["belief"]["counts"])==list(x["observation"]["facts"]["belief"]["counts"]),"prefix/public facts or menu drift")
        i=x["index"]
        if st["status"]=="choice":
            h=choice_b(st["facts"],st)
            history=m.advance(history,h,h["actions"][i])
            prefix["choices"].append(dict(at=len(prefix["trace"])-1,turn=h["turn"],kind=st["kind"],options=st["options"],selected=i))
        else:
            h=public_b(st["facts"])
            record_boundary(prefix,st["facts"],h,i)
            history=m.g2.encoder.update(history,h,h["actions"][i])
        prefix["actual_steps"]+=1
        st=host.call("step",index=i)
        if st.get("observed_c"):
            c=st["observed_c"]
            prefix["states"].append(strategic(c["facts"],c["draw"]))
    require(public(st)==r["prefix"]["root"] and list(st["facts"]["belief"]["counts"])==list(r["prefix"]["root"]["facts"]["belief"]["counts"]) and st["facts"]["turn"]==r["turn"],"target/public root drift")
    return st,history

def search(host,rank):
    return [g|dict(style=style) for style in ("light","guard","build","end")
            for g in host.call("search",indices=rank,style=style,limit=128)]

def plan_pair(graph,m,opening,case,role):
    unique={}
    projections={}
    for g in graph:
        q=m.backup([g],opening)[0]
        if q["value"] is None:continue
        law=return_law(g)
        ident=digest(law)
        if ident in unique:continue
        dist=defaultdict(float)
        projected=[defaultdict(float) for _ in range(4)]
        terminals={}
        for leaf in g["leaves"]:
            if leaf["kind"]=="C":
                c=strategic(leaf["facts"],leaf["draw"])
                case["states"][boundary_key("C",c)]=c
                k=key(c)
                features=[c["powers"],[c[z] for z in ("energy","hand","exhaust","draw_count")],c["enemies"],[c["hp"],c["block"]]]
            else:
                k=leaf["kind"]+"/"+str(leaf["hp"])
                terminals[boundary_key(leaf["kind"],leaf)]={i:leaf[i] for i in ("kind","hp","max_hp","gold")}
                features=[k]*4
            dist[k]+=leaf["mass"]
            for proj,val in zip(projected,features):proj[digest(val)]+=leaf["mass"]
        p=dict(first=g["index"],style=g["style"],then_end=g["style"]=="end",policy=g["policy"],law=dict(dist),public_law=law,value=q["value"],terminals=terminals)
        probability(law)
        unique[ident]=p
        projections[ident]=projected
    ordered=sorted(unique,key=lambda h:-unique[h]["value"])
    require(len(ordered)>=2,"two distinct complete laws unavailable")
    a=ordered[0]
    others=[h for h in ordered[1:] if unique[h]["law"]!=unique[a]["law"]]
    require(others,"two distinct encoded laws unavailable")
    def difference(h):
        return sum(any(abs(p.get(k,0)-q.get(k,0))>1e-8 for k in p.keys()|q.keys()) for p,q in zip(projections[a],projections[h]))
    b=max(others,key=difference) if role=="difference" else others[0]
    case["predicted_difference_channels"]=difference(b)
    return [unique[a],unique[b]]

def seed_for(slot,phase,i):
    return ((phase=="repeat")<<29) + (slot<<21) + (i<<18) + int(digest(["2a-world",phase,slot,i])[:5],16)%262144

def produce(host,m,r,phase,parent=None):
    t=time.perf_counter
    case=dict(prefix=blank(),worlds=[],natural_pair=[],states={},plans=[],status="failed",turn=r["turn"],cost={})
    cost=case["cost"]
    try:
        start=t()
        st,hist=recover(host,m,r,case)
        cost["recover"]=t()-start
        facts=st["facts"]
        opening={k:r["spec"][k] for k in ("hp","max_hp")}
        start=t()
        rank=m.rank(public_b(facts),hist,opening)
        graph=search(host,rank)
        case["plans"]=plan_pair(graph,m,opening,case,r["role"])
        case["graph_id"]=digest(graph)
        if parent:
            require(parent["plans"]==case["plans"] and parent["graph_id"]==case["graph_id"],"repeat plan drift")
            case["natural_pair"]=parent["natural_pair"]
        host.call("checkpoint")
        cost["discovery"]=t()-start
        for i in range(0 if parent else -1,4):
            seed=seed_for(r["slot"],phase,i) if i>=0 else None
            sides=[]
            if seed is None:case["natural_pair"]=sides
            else:case["worlds"].append(dict(seed=seed,outcomes=sides))
            for p in case["plans"]:
                row=blank()
                side=dict(trajectory=row,status="failed")
                sides.append(side)
                start=t()
                host.steps=[]
                timer="restore"
                try:
                    if i==0 and len(sides)==1:
                        changed=host.call("restore",world=seed,audit_rng=seed)
                        require(public(changed)==public(st) and digest(search(host,rank))==case["graph_id"],"private perturbation changed search")
                        case["invariant"]=True
                    sample=host.call("restore",**({} if seed is None else {"world":seed}))
                    require(public(sample)==public(st),"restore/public mismatch")
                    cost["restore"]=cost.get("restore",0)+t()-start
                    start=t()
                    timer="side_seconds"
                    fight(host,r["spec"],m,"tactical",32,row,resume=(sample,hist.copy()),first=p["first"],intervention_law=p["public_law"],intervention_policy=p["policy"],require_match=True)
                    cut=next(iter(row["states"]),None)
                    end=row["terminal"]
                    label=key(cut) if cut else row["status"]+"/"+str(end["hp"])
                    public_key=boundary_key("C",cut) if cut else boundary_key(row["status"],end)
                    side.update(status=row["status"],observed=label,matched=label in p["law"],public_key=public_key,public_matched=public_key in p["public_law"],utility=-50 if row["status"]=="Defeat" else float(payoff(torch.tensor(opening["hp"]-end["hp"]),torch.tensor(opening["max_hp"]))))
                    check_segment(dict(steps=host.steps),row,True)
                except FAIL as e:side["reason"]=str(e)[:500]
                finally:
                    cost[timer]=cost.get(timer,0)+t()-start
                    side["steps"]=host.steps if host.state is not None else []
        if all(s.get("matched") and s.get("public_matched") and "reason" not in s for pair in [case["natural_pair"],*[w["outcomes"] for w in case["worlds"]]] for s in pair):
            case["status"]="matched"
        else:case["status"]="law_or_execution_gap"
        case["eligible"]=qualify(case,dict(kind="conditional",worlds=4))
    except FAIL as e:
        if "recover" not in cost:cost["recover"]=t()-start
        elif "discovery" not in cost:cost["discovery"]=t()-start
        case.update(eligible=False,reason=str(e)[:500])
    if parent:case.pop("natural_pair")  # lineage references the frozen original pair
    return case
