"""Frozen public G2 reference and model-local inference reuse."""
import sys
from pathlib import Path
FIVE=Path(__file__).resolve().parent
sys.path.insert(0,str(FIVE.parent/"m1-core4"))
from improve import graph_plan, prepared, mass_kind
from semantic import encode, pack, torch, expected, tensor_row
from collections import deque, OrderedDict
from functools import lru_cache
from hashlib import sha256

def reference(lane,h,past,g2,limit=48,observe=None):
    ctrl=prepared(g2,h,past)
    def choose(obs,hist):
        index=int(ctrl.score([(obs,hist)])[0][0].argmax())
        if observe:observe(obs,hist,index)
        return index,g2.encoder.update(hist,obs,obs["actions"][index])
    first,hist=choose(h,ctrl.history)
    pending=deque([(1.,[dict(action=first,draws=[])],hist)])
    leaves=[]
    calls=0
    for _ in range(limit):
        if not pending:break
        p,route,hist=pending.popleft()
        r=lane.request("i1_core5_reference",route=route)["response"]
        calls+=r["calls"]
        if r["kind"]=="decision" and len(route)+len(past)<128:
            obs=lane.host.project(r["state"])
            action,after=choose(obs,hist)
            pending.append((p,route+[dict(action=action,draws=[])],after))
        elif r["kind"]=="R":
            support=r["support"];total=sum(support.values())
            for card,n in sorted(support.items(),key=lambda item:(-item[1],item[0])):
                edge=route[-1]
                pending.append((p*n/total,route[:-1]+[edge|dict(draws=edge["draws"]+[card])],hist))
        else:
            leaves.append(r|dict(probability=p))
    leaves.extend(dict(kind="deferred",probability=p) for p,_,_ in pending)
    if abs(sum(x["probability"] for x in leaves)-1)>1e-8:raise ValueError("Reference lost mass")
    return leaves,calls,first

@lru_cache(16384)
def cached_row(**fields):
    row=tensor_row(**fields)
    row.flags.writeable=False
    return row

class Evaluator:
    """Owned by one immutable deployment model. Cache distributions before opening-relative utility."""
    def __init__(self,net):
        self.net=net
        self.cache=OrderedDict()
        self.hits=self.misses=0

    @torch.inference_mode()
    def __call__(self,states,opening):
        if not states:return {}
        keys=[];missing={};prob={}
        for c in states.values():
            g,x=encode(c,row_fn=cached_row)
            key=sha256(g.tobytes()+x.tobytes()).digest()
            keys.append(key)
            if key in self.cache:
                prob[key]=self.cache[key];self.cache.move_to_end(key);self.hits+=1
            elif key in missing:self.hits+=1
            else:missing[key]=(g,x)
        if missing:
            batch=self.net(*pack(list(missing.values()))).softmax(-1)
            self.misses+=len(batch)
            for k,v in zip(missing,batch):
                self.cache[k]=prob[k]=v.clone()
                if len(self.cache)>2048:self.cache.popitem(last=False)
        vals=expected(torch.stack([prob[k] for k in keys]),torch.tensor(opening["hp"]),
                      torch.tensor([c["hp"] for c in states.values()]),torch.tensor(opening["max_hp"]))
        return dict(zip(states,vals.tolist()))

class Planner:
    def __init__(self,net,fast=True):
        self.evaluator=Evaluator(net) if fast else None
        self.fast=fast
        self.alternate_turn=None

    def __call__(self,lane,h,past,net,g2,opening):
        graph,choices,q=graph_plan(lane,h,past,net,g2,opening,direct=reference,
                                    evaluator=self.evaluator,fast=self.fast,alternatives=True)
        options=q.pop("options");ref=q.pop("ref_first")
        node=graph["nodes"][0]
        def index(j):return node["end"] if j==-1 else node["edges"][j]["input"]["index"]
        chosen=choices.get(0)
        actual=index(chosen) if q["use"] else ref
        # Search every fully covered comparison for the closest competing first action.
        rivals=[(v,j) for c,v,j in options if c>=1-1e-9 and index(j)!=actual]
        if q["use"] and ref!=actual:rivals.append((q["reference"],None))
        if rivals and q["reference_coverage"]>=1-1e-9:
            v,j=max(rivals,key=lambda t:t[0])
            q["alternative_value"]=v
            q["predicted_gap"]=(q["value"] if q["use"] else q["reference"])-v
            if self.alternate_turn==h["turn"]:
                q["use"]=j is not None
                if j is not None:choices[0]=j
        return graph,choices,q
