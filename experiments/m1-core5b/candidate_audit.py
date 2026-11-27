"""Locate the same strategic play sequence before and after A-settlement admission."""
from review import *
from collections import Counter

def main():
    t=perf_counter();d=json.load(gzip.open(E/"review-rescue.gz"));out=LOGS/"5b-candidate-audit";out.mkdir(exist_ok=True)
    result={}
    for arm in ("base","medium","high"):
        host,g2,net,plan=init(out,arm);lane=Lane(host,0);found={}
        def inspect(g,paths,laws,states,values,choices,opts,ref_law,first):
            if host.project(g["nodes"][0]["state"])["turn"]!=d["turn"]:return
            counts=Counter();mass=Counter()
            def visit(i,names,p):
                node=g["nodes"][i]
                if node["kind"]=="R":
                    for e in node["edges"]:visit(e["to"],names,p*e["probability"])
                elif node["kind"]=="decision":
                    if not names:
                        counts["represented"]+=1;mass["represented"]+=p
                        if i in laws:
                            counts["admitted"]+=1;mass["admitted"]+=p
                            mass["resolved"]+=p*sum(w for k,_,_,w in laws[i] if k in ("C","victory","death"))
                    else:
                        h=host.project(node["state"])
                        for e in node["edges"]:
                            a=description(h,e["input"]["index"])
                            if a["card"]==names[0]:visit(e["to"],names[1:],p)
            visit(0,["BASH","SHRUG_IT_OFF"],1.)
            found.update(nodes=len(g["nodes"]),possible_A=len(paths),settled_A=len(laws),counts=dict(counts),mass=dict(mass))
        plan.inspect=inspect
        # Base and high take identical actions before this root; force the common actual prefix for medium too.
        from play_loop import cohort,step
        trace=[];fight(lane,g2,d["spec"],"base",net,planner=Search(net,"base"),trace=trace);lane.reset()
        st=cohort.start(lane,d["spec"]);past=[]
        for h,a in trace:
            if h["turn"]==d["turn"]:break
            st=step(lane,st,a);past.append((h,a))
        plan(lane,host.project(st["observation"]),past,net,g2,d["spec"]);result[arm]=found;lane.close();host.close()
    (E/"candidate-audit.json").write_text(json.dumps(dict(rows=result,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":main()
