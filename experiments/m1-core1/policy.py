"""Compile an executable contingent policy and a joint B/terminal distribution."""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json

COMPLETE = {"B","predicted_win","death"}


def public_state(raw):
    if raw is None or "TerminalOutcome" not in raw:
        return raw
    return raw | dict(max_hp=raw["maxHp"],energy=raw["Energy"],gold=raw["Gold"],
                      enemies=[e | dict(hp=e["CurrentHp"],max_hp=e["MaxHp"],block=e["Block"])
                               for e in raw["enemies"]])


def address(path,observation):
    wire=json.dumps([path,observation],separators=(",",":")).encode()
    return hashlib.sha256(wire).hexdigest()


def choose(options):
    # Coverage first. The utility term only includes observed, resolved mass.
    covered=max(item[0] for item in options)
    return max((item for item in options if item[0]>=covered-1e-12),key=lambda item:item[1])


def exact_policy(graph,value,first=None):
    nodes=graph["Nodes"]
    rules={}

    @lru_cache(None)
    def visit(i):
        n=nodes[i]
        if not n["Edges"]:
            resolved=n["Kind"] in COMPLETE
            return int(resolved),value(n["Kind"],public_state(n["State"])) if resolved else 0.,{i:1.}
        options=[]
        for j,e in enumerate(n["Edges"]):
            if i==graph["root"] and first is not None and first!=j:
                continue
            options.append((*visit(e["To"]),j))
        if n["Kind"]=="chance":
            masses=defaultdict(float)
            coverage=score=0.
            for c,v,dist,j in options:
                p=n["Edges"][j]["Probability"]
                coverage+=p*c
                score+=p*v
                for k,w in dist.items():
                    masses[k]+=p*w
            return coverage,score,dict(masses)
        c,v,dist,j=choose(options)
        if n["Kind"] in ("choice","decision"):
            rules[i]=j
        return c,v,dist

    c,v,dist=visit(graph["root"])
    return dict(measure=graph["measure"],rules=rules,unseen="replan",coverage=c,value=v,
                successors=[dict(kind=nodes[i]["Kind"],state=public_state(nodes[i]["State"]),node=i,probability=w)
                            for i,w in dist.items()])


def sampled_policy(graph,value,first=None):
    # All candidates share the same indexed conditional world block. An edge
    # may be chosen only when every world in this information set evaluated it.
    starts=[]
    for p in graph["policies"]:
        for world,b in enumerate(p["branches"]):
            starts.append((world,b))
    if not starts:
        return None
    def visit(rows,depth,path):
        observations=defaultdict(list)
        leaves={}
        for world,b in rows:
            if len(b["witness"])==depth:
                leaf=(b["kind"],b["state"],b["probability"])
                if world in leaves and leaves[world]!=leaf:
                    raise ValueError("Inconsistent paired replay")
                leaves[world]=leaf
            else:
                observations[b["witness"][depth][0]].append((world,b))
        coverage=score=0.
        rules={}
        dist=[]
        states=graph["observations"]
        for world,(kind,state,w) in leaves.items():
            dist.append(dict(world=world,kind=kind,state=states.get(state),probability=w,witness=path))
            if kind in COMPLETE:
                coverage+=w
                score+=w*value(kind,states[state])
        for obs,group in observations.items():
            worlds={i for i,_ in group}
            by_action=defaultdict(list)
            for i,b in group:
                by_action[b["witness"][depth][1]].append((i,b))
            options=[]
            for action,sub in by_action.items():
                if depth==0 and first is not None and first!=action:
                    continue
                if {i for i,_ in sub}==worlds:
                    options.append((*visit(sub,depth+1,[*path,(obs,action)]),action))
            c,v,rr,dd,a=choose(options)
            coverage+=c
            score+=v
            rules.update(rr)
            rules[address(path,obs)]=a
            dist.extend(dd)
        return coverage,score,rules,dist

    c,v,rules,dist=visit(starts,0,[])
    if len(dist)!=graph["draws"] or len({s["world"] for s in dist})!=len(dist):
        raise ValueError("Selected strategy did not preserve the common sample")
    return dict(measure=graph["measure"],coverage=c,value=v,rules=rules,unseen="frozen_g2",successors=dist)


def compile_policy(graph,value,first=None):
    """first restricts the root edge to expose alternative candidate distributions."""
    compilers={"exact_conditional":exact_policy,"self_normalized_conditional_samples":sampled_policy}
    p=compilers[graph["measure"]](graph,value,first)
    if p is not None:
        p["unresolved_probability"]=max(0.,1.-p["coverage"]) if graph["measure"]=="exact_conditional" else None
    return p
