"""Paired sensitivity on any failed confirmation worlds using the isolated 5D replay fix."""
import json,gzip,sys
from time import perf_counter
from panel5e import E,OUT,ROOT,load,rows
from battle5e import setup_arm
from deploy5b import Lane,host_at,fight
def run(arm,indices):
    t=perf_counter();tag="repair-"+arm+"-"+"-".join(map(str,indices));out=OUT/tag
    out.mkdir(parents=True,exist_ok=True)
    old,g2,net,plan=setup_arm(out,arm);old.close()
    host=host_at(out,ROOT/"logs/core5d/replay-host");lane=Lane(host,0)
    panel=load(E/"panel.gz")["confirm"]
    with gzip.open(E/(tag+".gz"),"xt") as f:
        for i in indices:
            w=panel[i];s=w["spec"];last={};start=perf_counter()
            try:
                r=fight(lane,g2,s,arm,net,planner=plan,last=last);r.pop("states")
            except (RuntimeError,ValueError,IndexError,KeyError) as err:r=dict(status="error",error=repr(err),terminal=None,queries=[])
            lane.close()
            r.update(i=i,family=w["family"],seed=s["seed"],hp=s["hp"],max_hp=s["max_hp"],arm=arm,
                     turns=last.get("turn"),seconds=perf_counter()-start)
            f.write(json.dumps(r)+"\n")
    host.close();(E/(tag+".time.json")).write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":run(sys.argv[1],list(map(int,sys.argv[2:])))
