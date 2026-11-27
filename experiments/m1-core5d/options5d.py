"""Capture executable graph, reference and conditional policies from ONE normal 5C query."""
from collections import Counter
from functools import partial
from dataclasses import dataclass
from panel5d import digest
from complete import program,execute_program
from play_loop import execute,step,prepared
from policy5c import move
from turn_worlds import model_key
from improve import terminal

@dataclass
class Option:
    label:str
    first:str
    value:float
    law:list
    execute:object

def g2_turn(g2,lane,st,past):
    played=[]
    turn=lane.host.project(st["observation"])["turn"]
    while st["status"]=="active" and st["actions"]<128:
        h=lane.host.project(st["observation"])
        if h["turn"]!=turn:break
        ctrl=prepared(g2,h,past+played)
        ctrl.project=lane.host.project
        idx=ctrl.act(h,lane,st["actions"])[0]
        played.append((h,idx))
        st=step(lane,st,idx)
    return st,played,"end" if st["status"]=="active" else "terminal"

def menu(lane,h,past,net,g2,spec,planner):
    captured=[]
    def inspect(*args):captured.append(args)
    planner.detail=True
    planner.inspect=inspect
    try:g,ch,q=planner(lane,h,past,net,g2,spec)
    finally:planner.detail=False;planner.inspect=None
    turn=planner.last;planner.last=None
    graph,paths,laws,states,estimates,choices,opts,ref,first=captured[0]
    states=states|turn.states
    options=[]
    def register(label,index,value,law,executor):
        if any(k not in ("C","victory","death") for k,key,v,p in law) or abs(sum(z[3] for z in law)-1)>1e-8:return
        options.append(Option(label,move(h,h["actions"][index]),value,law,executor))
    nodes=graph["nodes"]
    def descend(i,forced=None,p=1.):
        node=nodes[i];kind=node["kind"]
        if kind=="decision":
            j=choices[i] if forced is None else forced
            if j==-1:
                for k,key,v,w in laws[i]:yield k,key,v,p*w
            else:yield from descend(node["edges"][j]["to"],p=p)
        elif kind=="R":
            for e in node["edges"]:yield from descend(e["to"],p=p*e["probability"])
        else:yield kind,None,terminal(kind,node["state"],spec),p
    for cov,value,j in opts:
        if cov<1-1e-9:continue
        index=nodes[0]["end"] if j==-1 else nodes[0]["edges"][j]["input"]["index"]
        register("graph/"+str(j),index,value,list(descend(0,j)),partial(execute,g=graph,choices=choices,first=j))
    if q["reference_coverage"]>=1-1e-9:
        register("G2",first,q["reference"],ref,lambda lane,st:g2_turn(g2,lane,st,past))
    for group in turn.records:
        for style,items in (group["proposals"]|{"chosen":group["chosen"]}).items():
            cov,value,_=turn.score(items)
            if cov<1-1e-9:continue
            index=next(a["index"] for a in h["actions"] if move(h,a)==group["first"])
            law=[(k,key if k=="C" else None,turn.values[key] if k!="C" else -50.,p) for p,k,key,_ in items]
            register(f"conditional/{index}/{style}",index,value,law,partial(execute_program,table=program(items)))
    main="G2" if not q["use"] else ("graph/"+str(ch[0]) if not q["conditional"] else None)
    if q["use"] and q["conditional"]:
        main=next(o.label for o in options if o.label.endswith("/chosen") and abs(o.value-q["value"])<1e-8)
    # Keep a complete representative per distribution in the frozen encoder, giving the actual action priority.
    keys={};canonical={};unique={}
    for opt in sorted(options,key=lambda o:o.label!=main):
        mass=Counter()
        for k,key,v,p in opt.law:
            if k=="C":
                if key not in keys:
                    keys[key]=model_key(states[key]);canonical[keys[key]]=states[key]
                mass[(k,keys[key],0.)]+=p
            else:mass[(k,None,v)]+=p
        opt.law=[(k,key,v,p) for (k,key,v),p in sorted(mass.items(),key=lambda z:repr(z[0]))]
        signature=tuple((k,key,round(v,5),round(p,10)) for k,key,v,p in opt.law)
        unique.setdefault(signature,opt)
    return list(unique.values()),canonical,main,q

def pair(options,states,main,prefer_same):
    if len(options)<2:return None
    def mixture(opt):
        x=Counter()
        for kind,key,u,p in opt.law:
            if kind!="C":
                x[kind]+=p*25;continue
            c=states[key]
            x["hp"]+=p*c["hp"];x["block"]+=p*c["block"]
            x["enemy"]+=p*sum(e["hp"] for e in c["enemies"])
            for power in c["powers"]:x["power/"+power["id"]]+=p*power["amount"]*3
            for key in ("top","bottom"):
                for name in c["belief"][key]:x[key+"/"+name]+=p*3
            for key in ("exhaust","hand"):
                for name in c[key]:x[key+"/"+str(name)]+=p
        return x
    features={o.label:mixture(o) for o in options}
    anchor=next((o for o in options if o.label==main),max(options,key=lambda o:o.value))
    # Admit same-first opportunities anywhere in the shared menu, including when G2 is incomplete.
    pairs=[(a,b) for i,a in enumerate(options) for b in options[i+1:] if
           (a.first==b.first if prefer_same else a is anchor or b is anchor)]
    if not pairs:pairs=[(anchor,b) for b in options if b is not anchor]
    def priority(ab):
        a,b=ab;left,right=features[a.label],features[b.label]
        diff=sum(abs(left[k]-right[k]) for k in left.keys()|right.keys())
        return (min(diff,35)+.24*min(a.value,b.value)-.2*abs(a.value-b.value),max(a.value,b.value))
    a,b=max(pairs,key=priority)
    return (a,b) if a.value>=b.value else (b,a)
