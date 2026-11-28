"""HotSearch public feedback adapter, using the existing frozen H5 executable."""
import sys
from pathlib import Path
from collections import Counter
H=Path(__file__).resolve().parent
E=H/"evidence"
W=H.parents[1]/"logs/core6b2"
sys.path.insert(0,str(H.parent/"m1-core6a"))
import search6 as s
from common6 import public_b,choice_b,sha,digest
from models import return_law
from proposals import select

RESEARCH=("target","general","expand")
class Actor(s.Actor):
    def __init__(self,mode):
        self.mode=mode
        super().__init__("low" if mode in RESEARCH else mode)
        self.visits=None

    def rank(self,menu,history,opening):
        ranked=super().rank(menu,history,opening)
        if self.visits is not None and len(ranked)>1:
            self.visits.append((menu,ranked))
        return ranked

    def identity(self,arm,limit,margin=0.):
        base=super().identity(arm,limit,margin)
        if self.mode not in RESEARCH:return base
        body=dict(schema="core6b2.public-branch.v1",arm=self.mode,parent=base["id"],
                  code={p:sha(H/p) for p in ("branch.py","proposals.py")},limit=limit,margin=margin)
        return body|dict(id=digest(body))

def explore(client,model,first,menu,history,opening,limit,change):
    memory={0:(model.advance(history,menu,menu["actions"][first]),False)}
    row=client.engine.send(dict(op="search",indices=[first],limit=limit,g2=True))
    while row["type"]=="g2":
        ticket=row["ticket"]
        try:
            hist,used=memory[row["parent"]]
            obs=choice_b(row["facts"],row["prompt"]) if row["prompt"] else public_b(row["facts"])
            if not used and obs==change.menu:
                index=change.index
                used=True
            else:
                index=model.rank(obs,hist,opening)[0]
            memory[ticket]=(model.advance(hist,obs,obs["actions"][index]),used)
        except Exception:
            client.engine.send(dict(op="g2",ticket=ticket,index=-1))
            raise
        row=client.engine.send(dict(op="g2",ticket=ticket,index=index))
    if not row["ok"]:raise RuntimeError(row["reason"])
    return row["result"][0]

def policy_key(graph):
    return tuple((e["parent"],e["view"],e["index"],e["node"]) for e in graph["policy"])

def differences(graph,baseline):
    """First differing edges on each common public path, in the new program's coordinates."""
    base={(e["parent"],e["view"]):e for e in baseline["policy"]}
    parents={0:0}
    changed=[]
    for e in graph["policy"]:
        if e["parent"] not in parents:continue
        old=base.get((parents[e["parent"]],e["view"]))
        if old is None or old["index"]!=e["index"]:
            changed.append([e["parent"],e["view"],e["index"]])
        else:parents[e["node"]]=old["node"]
    return changed

def portfolio(client,model,rank,opening,arm,limit):
    if model.mode not in RESEARCH:return s.portfolio(client,model,rank,opening,arm,limit)
    menu,history,_=model.context
    model.visits=[]
    try:
        groups=s.portfolio(client,model,rank,opening,arm,limit)
        visits=model.visits
    finally:model.visits=None
    ref=client.pending_ref[1]
    if ref["gaps"]:return groups
    if model.mode=="expand":
        ids=list(dict.fromkeys(g["index"] for g,_ in groups))
        for style in ("build","end"):
            graphs=client.call("search",indices=ids,limit=limit,style=style)
            groups.extend((g,q|dict(style="expand-"+style)) for g,q in zip(graphs,model.backup(graphs,opening),strict=True))
        return groups
    changes=select(visits,model.mode=="general")
    if not changes:return groups
    seen={policy_key(g) for g,_ in groups if not g["gaps"]}
    seen.add(policy_key(ref))
    new=[]
    for change in changes:
        graph=explore(client,model,rank[0],menu,history,opening,limit,change)
        model.metrics["deviation_graphs"]+=1
        model.metrics["deviation_steps"]+=graph["steps"]
        key=policy_key(graph)
        if not graph["gaps"] and key in seen:
            model.metrics["duplicate_closed_graphs"]+=1
            model.metrics["duplicate_steps"]+=graph["steps"]
            continue
        if not graph["gaps"]:seen.add(key)
        new.append((graph,change))
    # Models.backup indexes batched leaves by (first, leaf). Give sibling continuations distinct
    # temporary slots; restore the real legal first index before passing results to the engine.
    tagged=[g|dict(index=i) for i,(g,_) in enumerate(new)]
    values=model.backup(tagged,opening) if new else []
    if not new:return groups
    closed=[(ref,model.backup([ref],opening)[0])]+[(g,q) for g,q in groups if q["value"] is not None]
    incumbent=max(closed,key=lambda pair:pair[1]["value"])[0]
    known_values={tuple(sorted(return_law(g).items())):q["value"] for g,q in closed}
    for (graph,change),q in zip(new,values,strict=True):
        if not graph["gaps"]:
            law=tuple(sorted(return_law(graph).items()))
            q["value"]=known_values.setdefault(law,q["value"])
        groups.append((graph,q|dict(index=graph["index"],style="branch-"+change.kind,
                      old_action=change.incumbent,new_action=change.index,at_menu=digest(change.menu),
                      changed_edges=differences(graph,incumbent))))
    return groups
