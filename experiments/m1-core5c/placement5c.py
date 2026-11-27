"""Paired settlement placement at the exact same naturally visited 5B public decisions."""
import json,gzip
from time import perf_counter
from panel5c import OUT,E
from complete import setup,move
from deploy5b import Search,Lane,fight
from play_loop import cohort,step
def run():
    t=perf_counter()
    out=OUT/"placement"
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,plan=setup(out,"V2complete")
    lane=Lane(host,0)
    old=Search(net,"high")
    rows=[]
    for i,w in enumerate(json.load(gzip.open(E/"protocol.gz"))["regression"]):
        s=w["spec"]
        trace=[]
        fight(lane,g2,s,"high",net,planner=old,trace=trace)
        lane.reset()
        turns=sorted({h["turn"] for h,_ in trace if h["decision"]["phase"]=="combat"})
        turn=turns[min(i%5,len(turns)-1)]
        st=cohort.start(lane,s)
        past=[]
        for obs,idx in trace:
            if obs["turn"]==turn:
                break
            assert host.project(st["observation"])==obs
            past.append((obs,idx))
            st=step(lane,st,idx)
        h=host.project(st["observation"])
        eligible=set(move(h,a) for a in h["actions"])
        def capture(g,paths,laws,states,estimates,choices,opts,ref_law,first):
            node=g["nodes"][0]
            for c,v,j in opts:
                idx=node["end"] if j==-1 else node["edges"][j]["input"]["index"]
                if c>=1-1e-9:
                    legacy.add(move(h,h["actions"][idx]))
            sizes.update(old_ends=len(paths),old_allocated=len(laws),old_full=sum(
                all(k in ("C","death","victory") for k,_,_,p in law if p>0) for law in laws.values()))
        legacy=set()
        sizes={}
        old.inspect=capture
        _,_,qold=old(lane,h,past,net,g2,s)
        old.inspect=None
        plan.detail=True
        _,_,q=plan(lane,h,past,net,g2,s)
        more={r["first"] for r in plan.last.records if plan.last.score(r["chosen"])[0]>=1-1e-9}
        rows.append(dict(family=w["family"],seed=s["seed"],turn=turn,menu=len(eligible),old=len(legacy),
            combined=len(legacy|more),added=list(sorted(more-legacy)),**sizes,
            policy_ends=q["policy_ends"],settled_ends=q["settled_ends"],full=q["full_policies"],
            attempts=q["attempted_policies"],old_ref=qold["reference_coverage"],new_ref=q["reference_coverage"]))
        plan.last=None
        lane.reset()
    lane.close()
    host.close()
    (E/"placement.json").write_text(json.dumps(dict(seconds=perf_counter()-t,rows=rows),indent=2))
if __name__=="__main__":
    run()
