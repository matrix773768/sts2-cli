from search5 import FIVE,Planner
from play_loop import fight,load_net,graph_plan,setup,Lane,ROOT,cohort,digest,perf_counter
from search import host_at
from design import runtime
from pathlib import Path
import json,gzip,sys,time,os

def run(out,group,arm,rep,shard,n,cap=None):
    clock=time.perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    with gzip.open(FIVE/"evidence/panels.gz","rt") as f:jobs=json.load(f)[group]
    with gzip.open(out/"rows.gz","xt",encoding="utf8",compresslevel=4) as f:
        if arm in ("original","G2","G2search"):host,g2=setup(out)
        else:
            old,g2=runtime(out);old.close()
            host=host_at(out,ROOT/"logs/core5a-host3")
        lane=Lane(host,0)
        path=Path(os.environ.get("CORE5A_V2",FIVE/"evidence/v2.pt")) if arm=="v2" else FIVE.parent/"m1-core4/evidence/v1.pt"
        net=load_net(path,arm)
        plan=Planner(net,fast=arm!="slow") if arm in ("v1","fast","slow","v2") else graph_plan
        recent=0
        def play(spec):
            nonlocal recent
            try:
                counts={}
                row=fight(lane,g2,spec,arm,net,planner=plan,counts=counts)
                return row|dict(controller_counts=counts) if arm.startswith("G2") else row
            except (RuntimeError,ValueError,IndexError,KeyError) as error:
                recent+=1;lane.close();return dict(error=repr(error),terminal=None,states=[],queries=[])
            finally:
                if lane.client is not None:lane.reset()
        for i,j in enumerate(jobs[:cap]):
            if i%n!=shard:continue
            spec=j[1]|dict(seed=cohort.seed(j[3],f"core5a-{group}",rep))
            base=dict(family=j[3],hp=spec["hp"],max_hp=spec["max_hp"],seed=spec["seed"],
                      split="development" if group=="dev" else group)
            def record(r):f.write(json.dumps(base|r,separators=(",",":"))+"\n");f.flush()
            if isinstance(plan,Planner):plan.alternate_turn=None
            r=play(spec);record(r|dict(policy=arm))
            if arm=="v1" and group in ("dev","train") and (group=="dev" or i%2==0) and r["terminal"]:
                qs=[q for q in r["queries"] if "predicted_gap" in q]
                if qs:
                    q=min(qs,key=lambda x:(abs(x["turn"]-4),-abs(x["predicted_gap"])))
                    plan.alternate_turn=q["turn"]
                    alt=play(spec);record(alt|dict(policy="paired",skip=q["turn"],gap=q["predicted_gap"],main_used=q["used"]))
        lane.close();host.close()
    cache=getattr(plan,"evaluator",None)
    (out/"cost.json").write_text(json.dumps(dict(seconds=time.perf_counter()-clock,errors=recent,
        hits=cache.hits if cache else 0,misses=cache.misses if cache else 0)))
if __name__=="__main__":
    run(Path(sys.argv[1]),*sys.argv[2:4],*map(int,sys.argv[4:]))
