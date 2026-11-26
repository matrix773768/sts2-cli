"""Settle diverse A witnesses, evaluate qualified C in one batch and back up on the public graph."""
from collections import deque,defaultdict
from experience import *
from value_net import *
from search import ask,integrate,mass_kind,binding,comparable

def routes(graph):
    queue=deque([(0,[])])
    while queue:
        i,path=queue.popleft();n=graph["nodes"][i]
        if n["kind"]=="decision":
            if n["end"] is not None:yield i,path
            for e in n["edges"]:queue.append((e["to"],path+[dict(action=e["input"]["index"],draws=[])]))
        elif n["kind"]=="R":
            for e in n["edges"]:
                queue.append((e["to"],path[:-1]+[dict(action=path[-1]["action"],draws=path[-1]["draws"]+[e["input"]])]))

def terminal(kind,state,h):
    return -50. if kind=="death" else payoff(torch.tensor(h["hp"]-state["hp"]),torch.tensor(h["max_hp"])).item()

def compile_turn(lane,h,hist,net,arm,cap=48):
    g=ask(lane,h,hist,"reduced",160);nodes=g["nodes"]
    # Round-robin by first play; include long and short lines, without an A-value screen.
    buckets=defaultdict(list)
    for i,path in routes(g):buckets[path[0]["action"] if path else -1].append((i,path))
    for k in buckets:buckets[k].sort(key=lambda pair:digest(["core3",pair[1]]))
    picked=[]
    while len(picked)<cap and any(buckets.values()):
        for b in buckets.values():
            if b and len(picked)<cap:picked.append(b.pop())
    values={};states={};laws={};calls=g["calls"];cache={}
    for i,path in picked:
        result=integrate(lane,h,hist,dict(successors=[dict(kind="A",probability=1,route=path)]),
                         limit=8,cache=cache)
        calls+=result["calls"];law=[]
        for l in result["successors"]:
            k=mass_kind(l);s=l.get("state");key=None
            if k=="C":
                key=digest(s);states[key]=s
            law.append((k,key,terminal(k,s,h) if k in ("victory","death") else -50.,l["probability"]))
        laws[i]=law
    if states:values=dict(zip(states,predict(net,arm,list(states.values()),h)))
    backed={};choices={}
    def backup(i):
        if i in backed:return backed[i]
        n=nodes[i];kind=n["kind"]
        if kind=="decision":
            opts=[]
            if i in laws:
                opts.append((sum(p for k,_,_,p in laws[i] if k in ("C","victory","death")),
                             sum(p*values.get(key,v) for k,key,v,p in laws[i]),-1))
            for j,e in enumerate(n["edges"]):opts.append((*backup(e["to"]),j))
            c,u,idx=max(opts,key=lambda x:(round(x[0],9),x[1])) if opts else (0,-50,None)
            choices[i]=idx
        elif kind=="R":
            c=u=0.
            for e in n["edges"]:
                w=e["probability"];a,b=backup(e["to"]);c+=w*a;u+=w*b
        elif kind in ("death","victory"):c,u=1.,terminal(kind,n["state"],h)
        else:c,u=0.,-50.
        backed[i]=(c,u);return c,u
    cov,u=backup(0)
    options=[]
    if 0 in laws:
        options.append((-1,sum(p for k,_,_,p in laws[0] if k in ("C","victory","death")),
                        sum(p*values.get(key,v) for _,key,v,p in laws[0])))
    options.extend((j,*backup(e["to"])) for j,e in enumerate(nodes[0]["edges"]))
    options.sort(key=lambda o:(round(o[1],9),o[2]),reverse=True)
    return g,choices,options,dict(calls=calls,settlements=len(cache),unique_C=len(states),visited_A=len(picked),coverage=cov)

def execute(lane,st,g,choices,first):
    history=[];i=0
    while st["status"]=="active":
        n=g["nodes"][i];o=lane.host.project(st["observation"])
        if n["kind"]=="R":
            candidates=list(n["edges"]);match=[]
            while candidates:
                e=candidates.pop();m=g["nodes"][e["to"]]
                if m["kind"]=="R":candidates.extend(m["edges"])
                elif m["kind"]=="decision" and comparable(lane.host.project(m["state"]))==comparable(o):match.append(e["to"])
            if not match:return st,history,"observation_fallback"
            i=min(match);continue
        expected=lane.host.project(n["state"]) if n["kind"]=="decision" else {}
        if not expected or comparable(expected)!=comparable(o):return st,history,"menu_fallback"
        j=first if i==0 else choices.get(i)
        if j is None:return st,history,"unresolved"
        a=expected["actions"][n["end"]] if j==-1 else n["edges"][j]["input"]
        idx=next((a2["index"] for a2 in o["actions"] if binding(o,a2)==binding(expected,a)),None)
        if idx is None:return st,history,"binding_fallback"
        history.append((o,idx));st=step(lane,st,idx)
        if j==-1:return st,history,"end"
        i=n["edges"][j]["to"]
    return st,history,"terminal"
