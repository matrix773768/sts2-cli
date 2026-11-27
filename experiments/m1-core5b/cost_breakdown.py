"""Measure each budget at identical natural public roots, with actual transition accounting."""
from deploy5b import *
from play_loop import step,cohort,prepared
from collections import Counter

def main():
    t=perf_counter();out=LOGS/"5b-cost-breakdown";out.mkdir(exist_ok=True)
    host,g2,net,_=init(out,"base");lane=Lane(host,0)
    rows=[]
    for w in json.load(gzip.open(E/"panel.gz"))["historical"][::6]:
        s=cohort.start(lane,w["spec"]);past=[]
        while s["status"]=="active":
            h=host.project(s["observation"])
            if h["turn"]>=3:break
            ctrl=prepared(g2,h,past);ctrl.project=host.project
            idx,_,_=ctrl.act(h,lane,len(past));past.append((h,idx));s=step(lane,s,idx)
        if s["status"]=="active":
            for arm in ("base","medium","high","ref768"):
                transitions,limit,cap,exp=BUDGET[arm];count=Counter()
                class Meter:
                    def __init__(self):self.host=host
                    def request(self,key,**args):
                        r=lane.request(key,**args)
                        if key=="i1_core5_reference":
                            count["ref_requests"]+=1;count["ref_transitions"]+=r["response"]["calls"]
                        return r
                def stats(g,paths,laws,states,values,choices,opts,ref_law,first):
                    count.update(graph_transitions=g["calls"],generated_A=len(paths),selected_A=len(laws),unique_C=len(states))
                planner=Evaluator(net);started=perf_counter()
                try:
                    _,_,q=graph_plan(Meter(),h,past,net,g2,w["spec"],limit,direct=partial(reference,limit=cap),evaluator=planner,
                                     fast=True,transitions=transitions,expansions=exp,alternatives=True,inspect=stats)
                finally:lane.request("i1_core5_reference",clear=True)
                count["settle_transitions"]=q["calls"]-count["ref_transitions"]-count["graph_transitions"]
                rows.append(dict(family=w["family"],seed=w["spec"]["seed"],turn=h["turn"],arm=arm,counts=count,
                    seconds=perf_counter()-started,ref=q["reference_coverage"],value=q["value"]))
        lane.reset()
    lane.close();host.close()
    (E/"cost-breakdown.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":main()
