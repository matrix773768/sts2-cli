"""Strict complete-turn backup with a public G2 reference and combat-opening utility."""
from semantic import *
from turn_value import routes,execute,terminal
from search import ask,integrate,mass_kind,binding
from collections import defaultdict

def graph_plan(lane,h,past,net,g2,opening,limit=32,*,direct=None, evaluator=None, fast=False, alternatives=False):
    graph=ask(lane,h,past,"reduced",128);nodes=graph["nodes"]
    ref={};paths=dict(routes(graph))
    def reference(i,history):
        node=nodes[i];kind=node["kind"]
        if kind=="R":
            for e in node["edges"]:reference(e["to"],history)
        elif kind=="decision":
            obs=lane.host.project(node["state"]);ctrl=prepared(g2,obs,history)
            ctrl.project=lane.host.project
            scores=ctrl.score([(obs,ctrl.history)])[0][0];idx=int(np.argmax(scores))
            if idx==node["end"]:ref[i]=-1;return
            key=binding(obs,obs["actions"][idx])
            for j,e in enumerate(node["edges"]):
                if binding(obs,e["input"])==key:
                    ref[i]=j;reference(e["to"],history+[(obs,idx)]);break
    if direct is None:reference(0,list(past))
    selected=[i for i,j in ref.items() if j==-1]
    buckets=defaultdict(list)
    for i,path in paths.items():
        if i not in selected:buckets[path[0]["action"] if path else -1].append(i)
    for bucket in buckets.values():bucket.sort(key=lambda i:digest(paths[i]))
    while len(selected)<limit and any(buckets.values()):
        for b in buckets.values():
            if b and len(selected)<limit:selected.append(b.pop())
    cache={};states={};laws={};calls=graph["calls"]
    def register(leaves):
        law=[]
        for l in leaves:
            k=mass_kind(l);s=l.get("state");key=None
            if k=="C":key=digest(s);states[key]=s
            law.append((k,key,terminal(k,s,opening) if k in ("victory","death") else -50.,l["probability"]))
        return law
    if direct is not None:
        leaves,ref_calls,ref_first=direct(lane,h,past,g2)
        calls+=ref_calls
        ref_law=register(leaves)
    # Both the namespace and settlement cache live for exactly this public query.
    cache_scope=object() if fast else None
    if fast and selected:
        batch=lane.request("i1_core1r2",mode="settle_batch",routes=[paths[i] for i in selected],setup=[],budget=160)
        calls+=batch["calls"]
        for i,response in zip(selected,batch["results"],strict=True):
            key=(cache_scope,"settle_fast",json.dumps([paths[i],[]],sort_keys=True))
            cache[key]=response
    for i in selected:
        result=integrate(lane,h,past,dict(successors=[dict(kind="A",probability=1,route=paths[i])]),limit=8,cache=cache,fast=fast,cache_scope=cache_scope)
        calls+=result["calls"]
        laws[i]=register(result["successors"])
    estimates={}
    if evaluator is not None:
        estimates=evaluator(states,opening)
    elif states:
        cs=list(states.values())
        with torch.inference_mode():
            logits=net(*pack([encode(c) for c in cs]))
            vals=expected(logits.softmax(-1),torch.tensor(opening["hp"]),torch.tensor([c["hp"] for c in cs]),torch.tensor(opening["max_hp"]))
            estimates=dict(zip(states,vals.tolist()))
    choices={}
    root_options=[]
    def back(i,fixed):
        n=nodes[i];k=n["kind"]
        if k in ("death","victory"):return 1.,terminal(k,n["state"],opening)
        if k=="R":
            cc=uu=0.
            for e in n["edges"]:
                c,u=back(e["to"],fixed);p=e["probability"];cc+=c*p;uu+=u*p
            return cc,uu
        if k!="decision":return 0.,-50.
        options=[]
        if i in laws and (not fixed or ref.get(i)==-1):
            options.append((sum(p for k,_,_,p in laws[i] if k in ("C","victory","death")),sum(p*estimates.get(key,v)for _,key,v,p in laws[i]),-1))
        for j,e in enumerate(n["edges"]):
            if not fixed or ref.get(i)==j:options.append((*back(e["to"],fixed),j))
        if i==0 and not fixed:root_options.extend(options)
        cov,u,j=max(options,key=lambda t:(round(t[0],9),t[1])) if options else (0.,-50.,None)
        if not fixed:choices[i]=j
        return cov,u
    if direct is None:
        bc,bu=back(0,True)
    else:
        bc=sum(p for k,_,_,p in ref_law if k in ("C","victory","death"))
        bu=sum(p*estimates.get(key,v) for _,key,v,p in ref_law)
    ac,au=back(0,False)
    def probability_mass(policy):
        mass=defaultdict(float)
        def visit(i,p):
            n=nodes[i];kind=n["kind"]
            if kind=="R":
                for e in n["edges"]:visit(e["to"],p*e["probability"])
            elif kind=="decision":
                j=policy.get(i)
                if j==-1 and i in laws:
                    for leaf,_,_,weight in laws[i]:mass[leaf]+=p*weight
                elif j is not None and j>=0:visit(n["edges"][j]["to"],p)
                else:mass["no_witness"]+=p
            else:mass[n.get("reason") or kind]+=p
        visit(0,1.)
        if abs(sum(mass.values())-1)>1e-8:raise ValueError("Policy mass lost")
        return dict(mass)
    if direct is None: ref_mass=probability_mass(ref)
    else:
        ref_mass=defaultdict(float)
        for kind,_,_,p in ref_law:ref_mass[kind]+=p
    extra={}
    if alternatives:
        extra=dict(ref_first=ref_first,options=root_options)
    return graph,choices,dict(**extra,reference_coverage=bc,coverage=ac,reference=bu,value=au,
        reference_mass=ref_mass,candidate_mass=probability_mass(choices),
        use=ac>=1-1e-9 and bc>=1-1e-9 and au>bu+1.,calls=calls,settles=len(cache),unique=len(states))
