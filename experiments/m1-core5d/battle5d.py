"""Paired full battles and natural trajectories. Opening seed and family stay outside the policy."""
import gzip,json,sys
from time import perf_counter
from panel5d import E,OUT,load
from complete import setup,Planner
from deploy5b import Lane,init,fight,load_net
from policy5c import roots
def affordable(h):
    candidates=roots(h)
    unique=[]
    seen=set()
    for a in candidates:
        card=h["hand"][a["card"]]["id"]
        if card not in seen:
            seen.add(card)
            unique.append(a)
    return (unique+[a for a in candidates if a not in unique])[:2]
def configure(out,arm):
    if arm in ("G2","G2search","high"):return init(out,arm)
    host,g2,net,plan=setup(out,"V1complete" if arm=="V1" else "V2complete")
    if arm.startswith("V3") or arm.startswith("epoch"):
        path=E/"v3.pt" if arm.startswith("V3") else OUT/"full-fit"/(arm+".pt")
        net=load_net(path,arm)
        plan=Planner(net)
    if arm.endswith("low"):
        plan.graph_budget=(192,40,160,10)
        plan.admit=affordable
        plan.quotas=(24,56)
    return host,g2,net,plan
def run(group,arm,shard=0,n=1,*,evidence=E,logs=OUT,setup_arm=configure):
    start=perf_counter()
    tag=f"{group}-{arm}-{shard}"
    out=logs/tag
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,plan=setup_arm(out,arm)
    lane=Lane(host,0)
    panel=load(evidence/("augmentation.gz" if group in ("train2","dev2") else "panel.gz"))["confirm" if group=="cost" else group]
    if group=="cost":
        panel=[panel[6*i+i%2] for i in range(16)]
    natural=group in ("train","dev","train2","dev2")
    with gzip.open(evidence/(tag+".gz"),"xt",compresslevel=4) as f:
        for i in range(shard,len(panel),n):
            w=panel[i];s=w["spec"];before=perf_counter();trace=[];last={};counts={}
            try:
                r=fight(lane,g2,s,arm,net,planner=plan,trace=trace if natural else None,last=last,counts=counts)
                if natural:r["trace"]=[(h["turn"],a) for h,a in trace]
                else:r.pop("states")
                lane.reset()
            except (ValueError,RuntimeError,KeyError,IndexError) as exc:
                lane.close();r=dict(status="error",error=repr(exc),terminal=None,queries=[],states=[],trace=[])
            r.update(i=i,family=w["family"],seed=s["seed"],hp=s["hp"],max_hp=s["max_hp"],arm=arm,
                     turns=last.get("turn"),counts=counts,seconds=perf_counter()-before)
            f.write(json.dumps(r,separators=(",",":"))+"\n");f.flush()
    lane.close();host.close()
    (evidence/(tag+".time.json")).write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":run(*sys.argv[1:3],*map(int,sys.argv[3:]))
