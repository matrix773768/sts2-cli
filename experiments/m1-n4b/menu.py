"""Complete the single-action menu on the exact same accepted donors. Reuse identical recorded branches."""
from pathlib import Path
import sys
from time import perf_counter
from research import rollout
from design import LOGS,digest,jobs,position,read,runtime,write


def run(out,lo,hi):
    out.mkdir(parents=True,exist_ok=False)
    host,model=runtime(out)
    t=perf_counter()
    js=jobs()
    try:
        for j in js[lo:hi]:
            for n in j["counts"]:
                name=f"{j['id']:03}-{n}.json.gz"
                files=list(LOGS.glob("n4b-finalcore-*/"+name))
                if len(files)!=1:
                    raise ValueError(f"Missing or duplicate primary row {name}")
                r=read(files[0])
                extra={}
                if r["stop"]=="complete":
                    for block,ws in r["worlds"].items():
                        for w in ws:
                            old=w["results"]["0"]["outcomes"]
                            ys={}
                            for a in r["h"]["actions"]:
                                idx=a["index"]
                                path=[[digest(r["h"]),idx]]
                                if digest(path) in old:
                                    continue
                                lane=host.lane()
                                hist,h,st=position(lane,j,n,w)
                                if hist!=r["history"] or h!=r["h"]:
                                    raise ValueError("Mismatched conditional donor")
                                ys[str(idx)]=rollout(lane,model,hist,h,st,path,0)
                                lane.reset()
                            extra[w["seed"]]=ys
                write(out/name,dict(id=j["id"],counter=n,extra=extra))
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-t))


if __name__=="__main__":
    run(Path(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3]))
