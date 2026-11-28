"""Frozen reduced graph for deterministic Ironclad attacks, block and the exhaust selector.
The caller abandons the whole turn if any represented edge leaves this domain.
"""
from collections import Counter,deque
from copy import deepcopy
from lane import Unsupported
from wire import embedded

# role, frozen catalog entry, pure one-op attack/block
CARDS={"STRIKE_IRONCLAD":("attack",True,True),"TWIN_STRIKE":("attack",True,True),
       "DEFEND_IRONCLAD":("block",True,True),"IRON_WAVE":("mixed",True,False),
       "HEMOKINESIS":("attack",True,False),"BURNING_PACT":("special",False,False),
       "FORGOTTEN_RITUAL":("special",False,False)}
ORDER={"block":5,"attack":6,"mixed":7,"special":9}

def tactical(lane,mode,budget,**kw):
    prefixes=lane.prefixes
    lane.prefixes={}
    try:
        if mode=="reduced":return graph(lane,budget)
        if mode in ("settle_fast","settle_batch"):
            if kw.get("setup"):raise Unsupported("settlement/random_setup")
            routes=kw.get("routes",[kw.get("route",[])])
            seen=set();results=[]
            for route in routes:
                key=();calls=1;h=lane.opened
                for edge in route:
                    key+=((edge["action"],tuple(edge["draws"])),)
                    if key not in seen:calls+=1;seen.add(key)
                if key:h=lane.cache[key][1]
                r=lane.request("i1_core5_reference",route=route+[dict(action=len(h["actions"])-1,draws=[])])["response"]
                if r["kind"]!="C":raise Unsupported("settlement/"+r["kind"])
                results.append(dict(kind="C",state=r["state"],choices=[],calls=calls,approximate=False))
            if mode=="settle_batch":return dict(type="core1r2.settlement.v1",calls=sum(x["calls"] for x in results),results=results)
            return results[0]|dict(type="core1r2.settlement.v1",A=h)
        raise Unsupported("graph/mode/"+mode)
    finally:lane.prefixes=prefixes

def graph(lane,cap):
    nodes=[];front=[];counts=Counter();queue=deque();calls=0
    def empty(kind):
        return dict(kind=kind,at_call=0,state=None,belief=None,joint=None,end=None,effects=None,active=[],approximation=None,edges=[])
    def stop(reason):
        counts[reason]+=1;nodes.append(empty(reason));return len(nodes)-1
    def visit(key,h,f,sleep):
        n=empty("decision");idx=len(nodes);nodes.append(n)
        h=embedded(h);h["discard"].sort(key=lambda c:(c["id"],c["upgrade"]))
        for j,c in enumerate(h["discard"]):c["index"]=j
        joint=[f["hp"],f["block"],f["energy"],0,0,0,-f["enemy_hp"]]
        def dominates(a,b):return all(x>=y for x,y in zip(a,b))
        if not any(dominates(a,joint) for a in front):
            front[:]=[a for a in front if not dominates(joint,a)];front.append(joint)
        n.update(at_call=calls,state=h,joint=joint,end=len(h["actions"])-1,effects=[],
                 active=sorted(p["id"] for p in h["order_hooks"]),belief={k:f[k] for k in ("counts","top","bottom","shuffles")}|
                 dict(membership_gap=None,order_gap=None))
        moves=[]
        for j,a in enumerate(h["actions"][:-1]):
            c=f["hand"][a["card"]];name=c["id"]
            if name not in CARDS:raise Unsupported("graph/card/"+name)
            role,catalog,pure=CARDS[name];pv=a["preview"] or {};v=c["vars"]
            hits=pv.get("hits") or max(1,v.get("HitCount",1))
            dmg=(pv.get("damage_per_hit") or v.get("Damage",0))*hits
            block=pv.get("block") or v.get("Block",0)
            special=role=="special";target=a["target"] if a["target"] is not None else -1
            effect=dict(index=j,role=role,card=name,scope=target,source="catalog_and_dynamic" if catalog else "dynamic_and_exceptions",
                pure=pure,local_conflict=special,threshold=0,hits=hits,damage=dmg,block=block,draw=False)
            n["effects"].append(effect)
            counts["catalog_operations" if catalog else "dynamic_default"]+=1
            counts["generated_barrier" if special else "generated_classified"]+=1
            strength=block if role=="block" else dmg
            token=(role,name,c["upgrade"],target,a["cost"],a["star_cost"])
            moves.append((ORDER[role],-strength,token,j,pure,hits))
        if len(key)>=9:n["approximation"]="depth_cap";counts["depth_cap"]+=1;return idx
        seen=set()
        for order,neg,t,j,pure,hits in sorted(moves,key=lambda m:m[:2]):
            special=t[0]=="special";simple=t[0] in ("attack","block")
            if not special and t in sleep:counts["sleep_pruned"]+=1;continue
            if simple and t in seen:counts["duplicate_pruned"]+=1;continue
            seen.add(t)
            if pure and any(p and other[0]==t[0] and other[3:]==t[3:] and hit==hits and strength<neg
                            for _,strength,other,_,p,hit in moves):
                counts["dominance_pruned"]+=1;continue
            later=set() if special else sleep.copy()
            if not special:
                for od,strength,other,*_ in moves:
                    if other[0]!="special" and (od,strength,other)<(order,neg,t):
                        later.add(other);counts["canonical_constraints"]+=1
            queue.append((n,key,j,later))
        return idx
    visit((),lane.opened,lane.facts[lane.node],set())
    while queue:
        parent,key,j,sleep=queue.popleft()
        child=key+((j,()),)
        if calls>=cap:i=stop("budget")
        else:
            calls+=1
            route=[dict(action=a,draws=list(d)) for a,d in child]
            r=lane.request("i1_core5_reference",route=route)["response"]
            if child in lane.pending:i=stop("unsupported_pending_choice")
            elif r["kind"]=="decision":
                node,h,_=lane.cache[child];i=visit(child,h,lane.facts[node],sleep)
            else:raise Unsupported("graph/boundary/"+r["kind"])
        parent["edges"].append(dict(input=deepcopy(parent["state"]["actions"][j]),to=i,probability=None))
    return dict(type="core1r2.turn.v1",mode="reduced",nodes=nodes,no_draw_front=front,counts=dict(counts),
                calls=calls,forks=calls+1,milliseconds=0)
