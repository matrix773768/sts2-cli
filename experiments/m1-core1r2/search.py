"""Public request and conditional policy for the resident mechanism graph."""
from collections import Counter, defaultdict, deque
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-n4b"))
from design import CFG,Host,cohort,digest,read,write,step
from loop_battle import Lane

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


def ask(lane,h,hist,mode,budget):
    graph=lane.request("i1_core1r2",mode=mode,budget=budget)
    if graph["type"]=="core1r2.stop.v1":
        reason=graph["reason"]
        graph=dict(type="core1r2.turn.v1",nodes=[dict(kind=reason,state=h,belief=None,joint=None,
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
        if n["kind"]=="R":
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
        elif n["kind"]=="R":
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


def integrate(lane,h,history,plan,limit=32,*,previous=None,boundary="C",model_enemy=False,cache=None,fast=False,cache_scope=None):
    """Integrate up to limit additional settlement requests from the same public root and policy."""
    sources=(previous or plan)["successors"]
    pending_kind="deferred" if previous is not None else "A"
    pending=deque((s["probability"],s["route"],s.get("setup",[])) for s in sources if s["kind"]==pending_kind)
    leaves=[s for s in sources if s["kind"]!=pending_kind]
    events=list(previous["events"]) if previous is not None else []
    calls=previous["calls"] if previous is not None else 0
    rpc_seconds=0.
    stop_after=len(events)+limit
    cache={} if cache is None else cache
    mode="settle_b" if boundary=="B" else "settle_model" if model_enemy else "settle_c"
    if fast: mode="settle_fast"
    root_key=cache_scope if cache_scope is not None else (digest(h),digest(history))
    def replay(which,route,setup):
        nonlocal calls,rpc_seconds
        key=(root_key,which,json.dumps([route,setup],sort_keys=True))
        if key not in cache:
            started=perf_counter()
            cache[key]=lane.request("i1_core1r2",mode=which,budget=160,route=route,setup=setup)
            rpc_seconds+=perf_counter()-started
            calls+=cache[key]["calls"]
        return cache[key]
    while pending and len(events)<stop_after:
        p,route,setup=pending.popleft()
        r=replay(mode,route,setup)
        # A proxy can stand for a labeled C only. Verify chance laws and terminal stamps independently.
        if mode=="settle_model" and r["kind"] in ("R","victory","death"):
            r=replay("settle_c",route,setup)
        events.append(dict(route=route,setup=setup,probability=p,response=r))
        if r["kind"]=="R":
            total=sum(r["support"].values())
            likely_first=sorted(r["support"].items(),key=lambda item:(-item[1],item[0]))
            for card,n in reversed(likely_first):
                pending.appendleft((p*n/total,route,[*setup,card]))
        else:
            leaves.append(dict(kind=r["kind"],state=r.get("state"),belief=r.get("belief"),reason=r.get("reason"),approximate=r.get("approximate",False),choices=r.get("choices",[]),
                               probability=p,route=route,setup=setup))
    leaves.extend(dict(kind="deferred",route=route,setup=setup,probability=p) for p,route,setup in pending)
    if abs(sum(s["probability"] for s in leaves)-1)>1e-8:
        raise ValueError("Settlement lost probability mass")
    return dict(events=events,successors=leaves,calls=calls,rpc_seconds=rpc_seconds+(previous or {}).get("rpc_seconds",0.))


def mass_kind(leaf):
    kind=leaf["kind"]
    if kind=="C":
        if leaf.get("approximate"): return "C_model"
        law=leaf["state"]["belief"]
        return "C_partial" if law.get("membership_gap") or law.get("order_gap") else "C"
    if kind in ("victory","death","B"): return kind
    reason=leaf.get("reason") or kind
    if reason in ("budget","depth_cap","draw_depth_cap","deferred"): return "budget"
    if reason in ("unknown_draw_law","unqualified_draw_instances"): return "unknown_probability"
    return "mechanism:"+reason


def candidate(lane,h,history,g,*,value=None,limit=24,model_enemy=False):
    """Evaluate a bounded menu of public policies at C; the caller can supply a C value model."""
    cache={}
    def default(l):
        if l["kind"]=="victory": return 100000+l["state"]["hp"]
        if l["kind"]=="death": return -100000
        s=l["state"]
        return 2*s["hp"]-sum(e["hp"] for e in s["enemies"])+sum(
            2*p["amount"] for p in s["powers"] if p["id"] in ("STRENGTH_POWER","DEXTERITY_POWER","DEMON_FORM_POWER"))
    value=value or default
    base=policy(g)
    choices=[base]
    root=g["nodes"][0]
    # Select two distinct root alternatives by a public A score before the C comparison.
    def identity(p): return tuple((l["node"],l["probability"]) for l in p["successors"])
    seen={identity(base)}
    alternatives=[policy(g,first=e["input"]["index"]) for e in root["edges"]]
    if root["end"] is not None: alternatives.append(policy(g,first=root["end"]))
    for p in sorted(alternatives,key=lambda p:(p["tactical_coverage"],p["score"]),reverse=True):
        k=identity(p)
        if k not in seen:
            choices.append(p);seen.add(k)
        if len(choices)>=3: break
    evaluated=[]
    for p in choices:
        result=integrate(lane,h,history,p,limit,model_enemy=model_enemy,cache=cache)
        mass=Counter()
        u=0.
        for leaf in result["successors"]:
            k=mass_kind(leaf);mass[k]+=leaf["probability"]
            if k in ("C","C_partial","C_model","death","victory"): u+=leaf["probability"]*value(leaf)
        coverage=sum(mass[k] for k in ("C","C_partial","C_model","death","victory"))
        evaluated.append((coverage,u,p,result,dict(mass)))
    best=max(range(len(evaluated)),key=lambda i:(round(evaluated[i][0],10),evaluated[i][1],evaluated[i][2]["score"]))
    _,_,plan,result,_=evaluated[best]
    result=result|dict(selected=best,candidates=[dict(mass=m,value=u,score=p["score"],successors=r["successors"])
        for _,u,p,r,m in evaluated],all_calls=sum(r["calls"] for _,_,_,r,_ in evaluated),root_replays=len(cache),all_rpc_seconds=sum(r["rpc_seconds"] for _,_,_,r,_ in evaluated))
    plan=plan|dict(knowledge_options=sorted({id for l in result["successors"] for id in l.get("choices",[])}))
    return plan,result


def comparable(o):
    def row(c): return {k:v for k,v in c.items() if k!="index"}
    # Only the discard set is orderless. Native menu indices are rebound below.
    return {k:v for k,v in o.items() if k not in ("discard","actions")}|dict(
        discard=sorted((row(c) for c in o["discard"]),key=digest))


@lru_cache(maxsize=1)
def _rule_catalog():
    with gzip.open(HERE.parent/"m1-n1bc/catalog.json.gz","rt",encoding="utf8") as stream:
        catalog=json.load(stream)
    extension=json.loads((HERE/"rules.json").read_bytes())
    for group in ("graphs","cards"):
        if extension[group].keys() & catalog[group].keys():
            raise ValueError("Supplement conflicts with frozen catalogue")
        catalog[group].update(extension[group])
    return catalog


def rule_context(state):
    """Join a public C to frozen N1BC operations and enemy graphs, including explicit missing rules."""
    catalog=_rule_catalog()
    cards={c["id"] for zone in ("hand","discard","exhaust","deck") for c in state[zone]}
    cards.update(t.rsplit("#",1)[0] for t in state["belief"]["counts"])
    enemies={e["species"] for e in state["enemies"] if e.get("species")}
    return dict(cards={k:catalog["cards"].get(k) for k in sorted(cards)},
                graphs={k:catalog["graphs"].get(k) for k in sorted(enemies)})


def strategic_successors(graph,plan,settlement,history=()):
    """CORE-2/3 export for one candidate. Only completed leaves carry strategic target mass."""
    leaves=[leaf|dict(qualification=mass_kind(leaf)) for leaf in settlement["successors"]]
    mass=Counter()
    for leaf in leaves:
        mass[leaf["qualification"]]+=leaf["probability"]
    if abs(sum(mass.values())-1)>1e-8:
        raise ValueError("Incomplete successor accounting")
    return dict(schema="core1r2.strategic.v1",public_root=graph["nodes"][0]["state"],
        history=list(history),rule_catalog="experiments/m1-n1bc/catalog.json.gz",rule_catalog_extensions=["experiments/m1-core1r2/rules.json"],
        no_draw_front=list(frontier_witnesses(graph)),conditional_policy=plan,
        decisions_and_chance=graph["nodes"],settlement_events=settlement["events"],successors=leaves,mass=dict(mass),
        active_mechanisms=sorted({label for n in graph["nodes"] for label in n["active"]}),
        semantics=dict(discard="unordered_instances",draw_probability="qualified_without_replacement",
            primary_boundary="C",enemy_model_mass="conditional_path_mass_with_proxy_node",
            dominance="immediate_effect_heuristic" if graph["search_mode"]=="reduced" else "off",
            ordinary_draw="base_combinations" if graph["search_mode"]=="reduced" else "expand",
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
        if node["kind"]=="R": return st,"replan_draw"
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
            # Execute the same public selector used by the modeled EndTurn witness.
            while st["status"]=="active" and plan.get("knowledge_options"):
                menu=lane.host.project(st["observation"])
                dec=menu["decision"]
                if dec.get("effect")!="ApplyKnowledgeCurse": break
                actions=menu["actions"]
                selection=next((x for x in actions if x["kind"]=="confirm_selection"),None)
                if selection is None:
                    if not dec["candidates"] or dec["candidates"][0]["id"] not in plan["knowledge_options"]: break
                    selection=next(x for x in actions if x["kind"]=="select_candidate" and x["choice"]==0)
                hist.append((menu,selection["index"]))
                st=step(lane,st,selection["index"])
            if st["status"]!="active":return st,st["status"]
            after=lane.host.project(st["observation"])
            return st,"B" if is_next_decision(after,h["turn"]) else "pending_settlement"
        i=node["edges"][j]["to"]
