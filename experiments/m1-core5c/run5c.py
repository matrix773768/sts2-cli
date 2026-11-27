"""Run paired battles in the native simulator with the specified frozen planning interface."""
import sys,json,gzip
from time import perf_counter
from panel5c import HERE, E, OUT
from deploy5b import init, Lane, fight
from memory5c import peak
def run(group,arm,shard=None,n=None):
    start=perf_counter()
    tag=group+"-"+arm+(("-"+str(shard)) if shard is not None else "")
    out=OUT/tag
    out.mkdir(parents=True,exist_ok=True)
    panel=json.load(gzip.open(E/"protocol.gz"))
    worlds=panel["regression"][::2] if group=="cost" else panel[group]
    if arm.endswith("complete") or arm=="referenceOnly":
        from complete import setup
        host,g2,net,planner=setup(out,arm)
    else:
        host,g2,net,planner=init(out,arm)
    lane=Lane(host,0)
    try:
        with gzip.open(E/(tag+".gz"),"xt",compresslevel=3) as f:
            for i,w in enumerate(worlds):
                if shard is not None and i%int(n)!=int(shard):
                    continue
                spec=w["spec"]
                last={}
                t=perf_counter()
                try:
                    r=fight(lane,g2,spec,arm,net,planner=planner,last=last)
                    r.update(host_peak=peak(int(lane.client.proc._handle)),python_peak=peak())
                    lane.reset()
                    r.pop("states")
                except (RuntimeError,ValueError,KeyError,IndexError) as error:
                    lane.close()
                    r=dict(status="error",error=repr(error),terminal=None,queries=[])
                r.update(i=i,family=w["family"],seed=spec["seed"],hp=spec["hp"],max_hp=spec["max_hp"],
                    turns=last.get("turn"),seconds=perf_counter()-t)
                f.write(json.dumps(r,separators=(",",":"))+"\n")
                f.flush()
    finally:
        host.close()
        lane.close()
        (out/"seconds.json").write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":
    run(*sys.argv[1:])
