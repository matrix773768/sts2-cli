from panel import E,HERE,FIVE,ROOT,LOGS,records
from produce import fight,load_net,host_at,runtime,Lane,Planner
from search5 import reference,Evaluator,graph_plan
from functools import partial
from time import perf_counter
from pathlib import Path
import gzip,json,sys
BUDGET={"base":(128,32,48,8),"medium":(256,48,96,12),"high":(512,80,192,20),"V1high":(512,80,192,20)}
# Historical budget attribution. Hold the candidate graph and settlement caps fixed.
BUDGET["ref768"]=(128,32,768,8)
class Search:
    def __init__(self,net,arm):
        self.evaluator=Evaluator(net)
        self.arm=arm;self.inspect=None;self.force=None
    def __call__(self,lane,h,past,net,g2,spec):
        transitions,limit,cap,expansions=BUDGET[self.arm]
        try:
            g,ch,q=graph_plan(lane,h,past,net,g2,spec,limit,direct=partial(reference,limit=cap),
                fast=True,evaluator=self.evaluator,alternatives=True,transitions=transitions,expansions=expansions,inspect=self.inspect)
        finally:lane.request("i1_core5_reference",clear=True)
        if self.force and self.force[0]==h["turn"]:
            j=self.force[1];q["use"]=j is not None
            if j is not None:ch[0]=j
        return g,ch,q

def init(out,arm):
    old,g2=runtime(out);old.close()
    original=arm in ("G2","G2search","5A")
    host=host_at(out,ROOT/("logs/core5a-host3" if original else "logs/core5b-host"))
    net=load_net(FIVE.parent/"m1-core4/evidence/v1.pt" if arm=="V1high" else FIVE/"evidence/v2.pt",arm)
    plan=Planner(net) if original else Search(net,arm)
    return host,g2,net,plan

def run(group,arm,shard,n):
    start=perf_counter();tag=f"{group}-{arm}-{shard}";out=LOGS/"core5b"/tag;out.mkdir(parents=True,exist_ok=False)
    host,g2,net,plan=init(out,arm);lane=Lane(host,0)
    panel=json.load(gzip.open(E/"panel.gz","rt"))[group]
    with gzip.open(E/(tag+".gz"),"xt",compresslevel=3) as f:
        for i,w in enumerate(panel):
            if i%n!=shard:continue
            spec=w["spec"].copy()
            if group=="high":spec.update(hp=999,max_hp=999)
            last={};counts={};timer=perf_counter()
            try:
                r=fight(lane,g2,spec,arm,net,planner=plan,counts=counts,last=last);lane.reset()
                r.pop("states")
            except (RuntimeError,ValueError,KeyError,IndexError) as error:
                lane.close();r=dict(status="error",error=str(error),terminal=None,queries=[])
            r.update(i=i,family=w["family"],seed=spec["seed"],hp=spec["hp"],max_hp=spec["max_hp"],counts=counts,
                last_hp=last.get("hp"),turns=last.get("turn"),seconds=perf_counter()-timer)
            f.write(json.dumps(r,separators=(",",":"))+"\n");f.flush()
    host.close();lane.close();(E/(tag+".json")).write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(*sys.argv[1:3],*map(int,sys.argv[3:]))
