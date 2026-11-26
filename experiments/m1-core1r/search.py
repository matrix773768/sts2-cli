"""Public request and conditional policy for the resident mechanism graph."""
from collections import Counter, defaultdict, deque
from functools import lru_cache
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-n4b"))
from design import CFG,Host,cohort,digest,read,write,step
from loop_battle import Lane

SAFE=frozenset(json.loads((HERE/"belief_cards.json").read_bytes()))


def host_at(out,build):
    host=Host(out,build,CFG|dict(lane_recycles=256))
    base=host.project
    def public(wire):
        observation=cohort.project(base,wire)|dict(nunchaku=wire.get("nunchaku"))
        if wire.get("tuning_fork") is not None:
            observation["tuning_fork"]=wire["tuning_fork"]
        if wire.get("order_hooks"):
            observation["order_hooks"]=wire["order_hooks"]
        return observation
    host.project=public
    return host


def token(c):
    return c["id"]+"#"+str(c["upgrade"])


def belief(h,history):
    if any(c.get("enchantment") or c.get("affliction") for c in h["deck"]):
        return None
    if any(r not in ("BURNING_BLOOD","TUNING_FORK","NUNCHAKU") for r in h["relics"]):
        return None
    for o,a in history:
        action=o["actions"][a]
        if action["kind"]=="end_turn":
            continue
        if action["kind"]!="play_card" or o["hand"][action["card"]]["id"] not in SAFE:
            return None
    cards=Counter(token(c) for c in h["deck"])
    for zone in ("hand","discard","exhaust"):
        cards.subtract(token(c) for c in h[zone])
    if min(cards.values(),default=0)<0 or sum(cards.values())!=h["draw_count"]:
        return None
    return dict(sorted((c,n) for c,n in cards.items() if n))


def ask(lane,h,hist,mode,budget):
    graph=lane.request("i1_core1r",mode=mode,budget=budget,bag=belief(h,hist))
    if graph["type"]=="core1r.stop.v1":
        reason=graph["reason"]
        graph=dict(type="core1r.turn.v1",nodes=[dict(kind=reason,state=h,belief=None,joint=None,
                   end=None,active=[],approximation=None,edges=[])],no_draw_front=[],counts={reason:1},
                   calls=0,forks=0,milliseconds=0)
    return graph | dict(search_mode=mode,transition_budget=budget)


def frontier_witnesses(graph):
    """One executable no-extra-draw route per retained joint vector, with its public A."""
    todo=[(0,[])]
    wanted={tuple(point) for point in graph["no_draw_front"]}
    while wanted and todo:
        i,route=todo.pop()
        n=graph["nodes"][i]
        if n["kind"]!="decision":
            continue
        point=tuple(n["joint"])
        if point in wanted:
            wanted.remove(point)
            yield dict(node=i,joint=n["joint"],state=n["state"],route=route,end=n["end"])
        for edge in reversed(n["edges"]):
            todo.append((edge["to"],[*route,dict(action=edge["input"]["index"],draws=[])]))
    if wanted:
        raise ValueError("Unwitnessed no-draw frontier")

def score(kind,p,root):
    if kind=="death": return -100000.
    if kind=="victory": return 100000.+p[0]
    incoming=sum(sum(e["attack_hits"]) for e in root["enemies"])
    return 2*p[0]+min(incoming,p[1])+0.05*p[1]+sum(p[6:])+2*sum(p[3:6])


def policy(graph,value=None,*,first=None,boundary_values=None):
    """Compile an observation policy. Optionally fix one root action or supply CORE-3 values by A node."""
    nodes=graph["nodes"]
    root=nodes[0]["state"]
    value=value or (lambda kind,p:score(kind,p,root))
    rules={}
    @lru_cache(None)
    def visit(i):
        n=nodes[i]
        if n["kind"] in ("victory","death"):
            return 1.,value(n["kind"],n["joint"]),{i:1.}
        if n["kind"]=="C":
            mass=defaultdict(float)
            c=v=0.
            for e in n["edges"]:
                coverage,u,leaves=visit(e["to"])
                w=e["probability"]
                c+=w*coverage
                v+=w*u
                for leaf,p in leaves.items(): mass[leaf]+=w*p
            if abs(sum(mass.values())-1)>1e-9: raise ValueError("Missing chance mass")
            return c,v,dict(mass)
        if n["kind"]!="decision":
            return 0.,0.,{i:1.}
        opts=[]
        if n["end"] is not None and (i!=0 or first in (None,n["end"])):
            a_value=(boundary_values or {}).get(i)
            opts.append((1.,value("A",n["joint"]) if a_value is None else a_value,{i:1.},-1))
        for j,e in enumerate(n["edges"]):
            if i==0 and first is not None and first!=e["input"]["index"]:
                continue
            cov,u,out=visit(e["to"])
            opts.append((cov,u-.0001,out,j))
        if not opts:
            raise ValueError("Requested action outside the emitted candidate menu")
        c,v,leaves,choice=max(opts,key=lambda t:(round(t[0],12),t[1]))
        rules[i]=choice
        return c,v,leaves
    coverage,value_,masses=visit(0)
    paths=[]
    def routes(i,route):
        n=nodes[i]
        if n["kind"]=="decision" and rules[i]!=-1:
            e=n["edges"][rules[i]]
            routes(e["to"],[*route,dict(action=e["input"]["index"],draws=[])])
        elif n["kind"]=="C":
            for e in n["edges"]:
                routes(e["to"],[*route[:-1],dict(action=route[-1]["action"],draws=[*route[-1]["draws"],e["input"]])])
        else:
            paths.append(dict(node=i,state=n["state"],belief=n.get("belief"),joint=n["joint"],
                              kind="A" if n["kind"]=="decision" else n["kind"],
                              probability=masses[i],route=route))
    routes(0,[])
    deferred=sum(p["probability"] for p in paths if p["kind"]=="A")
    return dict(rules=rules,tactical_coverage=coverage,score=value_,unresolved_tactical_mass=max(0,1.-coverage),
                deferred_end_turn_mass=deferred,modeled_complete_mass=max(0,coverage-deferred),successors=paths)


def integrate(lane,h,history,plan,limit,*,previous=None):
    """Integrate up to limit additional settlement requests from the same public root and policy."""
    sources=(previous or plan)["successors"]
    pending_kind="deferred" if previous is not None else "A"
    pending=deque((s["probability"],s["route"],s.get("setup",[])) for s in sources if s["kind"]==pending_kind)
    leaves=[s for s in sources if s["kind"]!=pending_kind]
    events=list(previous["events"]) if previous is not None else []
    calls=previous["calls"] if previous is not None else 0
    stop_after=len(events)+limit
    bag=belief(h,history)
    while pending and len(events)<stop_after:
        p,route,setup=pending.popleft()
        r=lane.request("i1_core1r",mode="settle",bag=bag,budget=160,route=route,setup=setup)
        calls+=r["calls"]
        events.append(dict(route=route,setup=setup,probability=p,response=r))
        if r["kind"]=="C":
            total=sum(r["support"].values())
            likely_first=sorted(r["support"].items(),key=lambda item:(-item[1],item[0]))
            for card,n in reversed(likely_first):
                pending.appendleft((p*n/total,route,[*setup,card]))
        else:
            leaves.append(dict(kind=r["kind"],state=r.get("state"),belief=r.get("belief"),reason=r.get("reason"),
                               probability=p,route=route,setup=setup))
    leaves.extend(dict(kind="deferred",route=route,setup=setup,probability=p) for p,route,setup in pending)
    if abs(sum(s["probability"] for s in leaves)-1)>1e-8:
        raise ValueError("B integration lost probability mass")
    return dict(events=events,successors=leaves,calls=calls)


def comparable(o):
    def row(c): return {k:v for k,v in c.items() if k!="index"}
    # Only the discard set is orderless. Native menu indices are rebound below.
    return {k:v for k,v in o.items() if k not in ("discard","actions")}|dict(
        discard=sorted((row(c) for c in o["discard"]),key=digest))


def strategic_successors(graph,plan,settlement):
    """CORE-2/3 export for one candidate. Only completed leaves carry strategic target mass."""
    leaves=settlement["successors"]
    mass=Counter()
    for leaf in leaves:
        kind=leaf["kind"]
        group=kind if kind in ("B","victory","death","deferred") else "unresolved"
        mass[group]+=leaf["probability"]
    if abs(sum(mass.values())-1)>1e-8:
        raise ValueError("Incomplete successor accounting")
    return dict(schema="core1r.strategic.v1",public_root=graph["nodes"][0]["state"],
        no_draw_front=list(frontier_witnesses(graph)),conditional_policy=plan,
        decisions_and_chance=graph["nodes"],settlement_events=settlement["events"],successors=leaves,mass=dict(mass),
        active_mechanisms=sorted({label for n in graph["nodes"] for label in n["active"]}),
        semantics=dict(discard="unordered_instances",draw_probability="qualified_without_replacement",
            dominance="immediate_effect_heuristic" if graph["search_mode"]=="reduced" else "off",
            ordinary_draw="end_turn_only" if graph["search_mode"]=="reduced" else "expand",
            joint_axes=["player_hp","block","energy","strength","dexterity","demon_form","negative_hp_per_enemy"],
            frontier_scope="visited_no_extra_draw_nonterminal_decisions"),
        search_mode=graph["search_mode"],budget=graph["transition_budget"],events=graph["counts"],
        tactical_calls=graph["calls"],settlement_calls=settlement["calls"])

def binding(o,a):
    key={k:a.get(k) for k in ("kind","card","target","target_side","choice","choice_zone","potion")}
    if a.get("choice_zone")=="discard" and a.get("choice") is not None:
        pos=a["choice"]
        card=o["discard"][pos]
        key["choice"]=({k:v for k,v in card.items() if k!="index"},
                       sum(token(c)==token(card) for c in o["discard"][:pos]))
    return digest(key)


def is_next_decision(o,from_turn):
    return (o["turn"]==from_turn+1 and o["decision"]["phase"]=="combat" and bool(o["enemies"])
            and any(a["kind"]=="end_turn" for a in o["actions"]))

def execute(lane,st,hist,graph,plan):
    """Execute public witnesses until A settles, terminal, or a newly observed random menu."""
    i=0
    while True:
        node=graph["nodes"][i]
        if node["kind"]=="C": return st,"replan_draw"
        if node["kind"] in ("victory","death"): return st,node["kind"]
        if node["kind"]!="decision": return st,"unresolved"
        h=lane.host.project(st["observation"])
        expected=lane.host.project(node["state"])
        if comparable(h)!=comparable(expected): return st,"witness_mismatch"
        rules=plan["rules"]
        j=rules[i] if i in rules else rules[str(i)]
        target=expected["actions"][node["end"]] if j==-1 else node["edges"][j]["input"]
        bound=binding(expected,target)
        act=next((a for a in h["actions"] if binding(h,a)==bound),None)
        if act is None: return st,"witness_mismatch"
        a=act["index"]
        hist.append((h,a))
        st=step(lane,st,a)
        if st["status"]!="active": return st,st["status"]
        if j==-1:
            after=lane.host.project(st["observation"])
            return st,"B" if is_next_decision(after,h["turn"]) else "pending_settlement"
        i=node["edges"][j]["to"]
