"""Locate the key-card filter relative to pending choices, third draw and A admission."""
from turn_graph_audit import *
from turn_lines import CONFIRM

class Switch:
    def __init__(self,lane,enabled):
        self.lane=lane;self.host=lane.host;self.enabled=enabled
    def request(self,key,**args):
        if key=="i1_core1r2" and args.get("mode") in ("reduced","tree"):
            args["review_third_draw"]=self.enabled
        return self.lane.request(key,**args)

def observed_after_draw(graph,lane):
    root=graph["nodes"][0];h=lane.host.project(root["state"])
    first=next((e for e in root["edges"] if move_at(h,e["input"]["index"])==TRANCE),None)
    rows=[]
    def visit(i,p,events):
        n=graph["nodes"][i]
        if n["kind"]=="R":
            for e in n["edges"]:visit(e["to"],p*e["probability"],events+[e["input"]])
        elif n["kind"]=="decision":
            o=lane.host.project(n["state"])
            rows.append(dict(events=events,p=p,approx=n.get("approximation"),legal=list(choices(o)),
                edges=[move_at(o,e["input"]["index"]) for e in n["edges"]],energy=o["energy"]))
        else:rows.append(dict(events=events,p=p,reason=n["kind"]))
    if first:visit(first["to"],1.,[])
    return rows

def run():
    start=perf_counter();d=source("loss");probe=json.load(gzip.open(E/"turn-probe-loss.gz"))
    out=LOGS/"turn-filter";out.mkdir(exist_ok=True)
    old,g2,v2,_=init(out,"high");old.close()
    host=host_at(out,ROOT/"logs/core5b-turn-filter-host");lane=Lane(host,0)
    past=prefix(lane,g2,v2,d);st=restore(lane,d,past);all_rows={}
    def inspect(include,third,arm):
        h=host.project(st["observation"]);proxy=Switch(lane,third)
        if arm=="tree":
            g=ask(proxy,h,past,"tree",512)
            return dict(policies={k:trace_graph(lane,g,None,probe,k) for k in include},reveals=observed_after_draw(g,lane))
        plan=Search(v2,arm);record={}
        def collect(g,paths,laws,*_):
            record.update(policies={k:trace_graph(lane,g,laws,probe,k) for k in include},reveals=observed_after_draw(g,lane))
        plan.inspect=collect;plan(proxy,h,past,v2,g2,d["spec"]);return record
    stages=[("root",("adaptive_v2","trance_static")),("after_choice",("after_choice",)),("after_trance",("after_trance",))]
    probe["lines"].update(after_choice=dict(moves=(TRANCE,IMP)),after_trance=dict(moves=(IMP,)))
    for stage,include in stages:
        if stage=="after_choice":steps=(HEAD,("pick","IMPERVIOUS",1),CONFIRM)
        elif stage=="after_trance":steps=(TRANCE,)
        else:steps=()
        for move in steps:
            h=host.project(st["observation"]);a=choices(h)[move];past.append((h,a));st=step(lane,st,a)
        all_rows[stage]=dict(law=st["public_law"],h=host.project(st["observation"]),arms={})
        for third,arm in ((False,"high"),(True,"high"),(True,"tree")):
            all_rows[stage]["arms"][f"third={third}/{arm}"]=inspect(include,third,arm)
    host.close();lane.close()
    with gzip.open(E/"turn-filter.gz","wt") as f:json.dump(dict(rows=all_rows,seconds=perf_counter()-start),f,separators=(",",":"))
if __name__=="__main__":run()
