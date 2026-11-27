"""Measure probability reaching each requested plan in the submitted graph and settlement allocation."""
import sys
from turn_probe import *
from search import ask
from turn_value import routes

def move_at(obs,idx):
    desc=description(obs,idx)
    if desc["kind"]=="play_card":return (desc["card"],desc["upgrade"],desc["target"])
    if desc["kind"]=="select_candidate":
        c=obs["decision"]["candidates"][desc["choice"]];return ("pick",c["id"],c["upgrade"])
    return (desc["kind"],)

def trace_graph(lane,graph,laws,probe,name):
    adaptive=name.startswith("adaptive")
    initial=[SHRUG if probe["tag"]=="rescue" else TRANCE] if adaptive else probe["lines"][name]["moves"]
    blocked=Counter();counts=Counter();result=Counter();samples={}
    def visit(i,p,rest,observed=False,cheap=False):
        n=graph["nodes"][i];kind=n["kind"]
        if kind=="R":
            for e in n["edges"]:visit(e["to"],p*e["probability"],rest,observed,cheap)
            return
        if kind!="decision":
            blocked[kind]+=p;return
        h=lane.host.project(n["state"])
        if observed:
            rest=probe["reveal"][hand_key(h)]["best"][int(name=="adaptive_v2")]
        action,tail=select(h,rest);action=tuple(action);counts[str(action)]+=p
        if action==END:
            result["generated"]+=p
            if laws is not None and i in laws:
                result["admitted"]+=p
                result["settled"]+=p*sum(w for k,_,_,w in laws[i] if k in ("C","victory","death"))
            return
        cheap=cheap or n.get("approximation")=="ordinary_combinations"
        edges=[e for e in n["edges"] if move_at(h,e["input"]["index"])==action]
        if not edges:
            legal=choices(h);effect=next((v for v in n.get("effects",[]) if v["index"]==legal.get(action)),{})
            reason="ordinary_skip" if graph["search_mode"]=="reduced" and cheap and (effect.get("role")=="special" or effect.get("draw")) else "missing_edge"
            blocked[reason]+=p
            samples.setdefault(reason,dict(action=action,role=effect.get("role"),approximation=n.get("approximation"),hand=hand_key(h)))
            return
        # Equivalent duplicate copies only count once. The root menus here contain at most
        # one emitted binding for each requested simple play after duplicate reduction.
        visit(edges[0]["to"],p,tail,adaptive and i==0,cheap)
    visit(0,1.,initial)
    assert abs(result["generated"]+sum(blocked.values())-1)<1e-8
    return dict(mass=dict(result),blocked=dict(blocked),visited=dict(counts),examples=samples)

def run(tag):
    t=perf_counter();d=source(tag);probe=json.load(gzip.open(E/f"turn-probe-{tag}.gz"))
    out=LOGS/f"turn-graph-{tag}";out.mkdir(exist_ok=True);host,g2,v2,_=init(out,"high");lane=Lane(host,0)
    past=prefix(lane,g2,v2,d);st=restore(lane,d,past);h=host.project(st["observation"])
    v1=load_net(FIVE.parent/"m1-core4/evidence/v1.pt","V1high")
    rows={}
    for arm in ("base","medium","high"):
        result={}
        for label,net in (("V1",v1),("V2",v2)):
            plan=Search(net,arm)
            def inspect(g,paths,laws,states,values,choices_,opts,ref_law,ref_first):
                node=g["nodes"][0]
                result[label]=[dict(first=move_at(h,node["end"] if j==-1 else node["edges"][j]["input"]["index"]),coverage=c,value=v) for c,v,j in opts]
                if label=="V2":
                    result["policies"]={name:trace_graph(lane,g,laws,probe,name) for name in probe["lines"]}
                    result["graph"]=dict(counts=g.get("counts"),calls=g["calls"],possible_A=len(paths),selected_A=len(laws))
            plan.inspect=inspect;_,_,q=plan(lane,h,past,net,g2,d["spec"])
            result[label+"_reference"]=dict(coverage=q["reference_coverage"],value=q["reference"])
        rows[arm]=result
    for mode,budget in (("reduced",4096),("tree",4096)):
        g=ask(lane,h,past,mode,budget)
        rows[f"{mode}-{budget}"]=dict(graph=dict(calls=g["calls"],counts=g["counts"]),
                     policies={name:trace_graph(lane,g,None,probe,name) for name in probe["lines"]})
    lane.close();host.close()
    (E/f"turn-graph-{tag}.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":run(sys.argv[1])
