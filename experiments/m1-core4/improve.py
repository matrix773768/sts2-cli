"""Strict complete-turn backup with a public G2 reference and combat-opening utility."""
from semantic import *
from turn_value import routes,execute,terminal
from search import ask,integrate,mass_kind,binding
from collections import defaultdict

def graph_plan(lane,h,past,net,g2,opening,limit=32):
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
    reference(0,list(past))
    selected=[i for i,j in ref.items() if j==-1]
    buckets=defaultdict(list)
    for i,path in paths.items():
        if i not in selected:buckets[path[0]["action"] if path else -1].append(i)
    for bucket in buckets.values():bucket.sort(key=lambda i:digest(paths[i]))
    while len(selected)<limit and any(buckets.values()):
        for b in buckets.values():
            if b and len(selected)<limit:selected.append(b.pop())
    cache={};states={};laws={};calls=graph["calls"]
    for i in selected:
        result=integrate(lane,h,past,dict(successors=[dict(kind="A",probability=1,route=paths[i])]),limit=8,cache=cache)
        calls+=result["calls"];law=[]
        for l in result["successors"]:
            k=mass_kind(l);s=l.get("state");key=None
            if k=="C":key=digest(s);states[key]=s
            law.append((k,key,terminal(k,s,opening) if k in ("victory","death") else -50.,l["probability"]))
        laws[i]=law
    estimates={}
    if states:
        cs=list(states.values())
        with torch.inference_mode():
            logits=net(*pack([encode(c) for c in cs]))
            vals=expected(logits.softmax(-1),torch.tensor(opening["hp"]),torch.tensor([c["hp"] for c in cs]),torch.tensor(opening["max_hp"]))
            estimates=dict(zip(states,vals.tolist()))
    choices={}
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
        cov,u,j=max(options,key=lambda t:(round(t[0],9),t[1])) if options else (0.,-50.,None)
        if not fixed:choices[i]=j
        return cov,u
    bc,bu=back(0,True);ac,au=back(0,False)
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
    return graph,choices,dict(reference_coverage=bc,coverage=ac,reference=bu,value=au,
        reference_mass=probability_mass(ref),candidate_mass=probability_mass(choices),
        use=ac>=1-1e-9 and bc>=1-1e-9 and au>bu+1.,calls=calls,settles=len(cache),unique=len(states))
