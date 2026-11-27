"""Evaluate the original development failure on the isolated diagnostic host."""
import json
from time import perf_counter
from panel5d import E,OUT,load,rows
from battle5d import configure
from complete import host_at
from deploy5b import Lane,fight
def run():
    t=perf_counter();out=OUT/"fault-check";out.mkdir(parents=True,exist_ok=True)
    old,g2,net,plan=configure(out,"V2");old.close()
    host=host_at(out,OUT/"replay-host");lane=Lane(host,0)
    result=[]
    for group in ("dev","train","train2"):
        spec=load(E/("augmentation.gz" if group=="train2" else "panel.gz"))[group]
        for file in E.glob(group+"-V2-*.gz"):
            for r in rows(file):
                if r["status"]!="error":continue
                try:
                    b=fight(lane,g2,spec[r["i"]]["spec"],"V2",net,planner=plan)
                    after=dict(status=b["status"],actions=b["actions"],terminal=b["terminal"])
                except (ValueError,RuntimeError) as exc:after=dict(error=str(exc))
                result.append(dict(group=group,i=r["i"],seed=r["seed"],before=r["error"],after=after))
                lane.close()
    host.close()
    (E/"replay-check.json").write_text(json.dumps(dict(cases=result,seconds=perf_counter()-t,
        build=json.loads((OUT/"replay-host/build.json").read_bytes())),indent=2))
if __name__=="__main__":run()
