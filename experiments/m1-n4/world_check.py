"""Offline exact world identity at construction on repeated independent starts, outside actor input."""
from pathlib import Path
import sys
from time import perf_counter
from cohort import ROOT, digest, plan, prefix, read, runtime, write


def run(out):
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    host,model=runtime(out)
    t=perf_counter()
    rows=[]
    for j in [plan()[i] for i in (0,1,2,96,97)]:
        r=read(ROOT/f"logs/n4-v2-{j[2]}/{j[0]:03}.json.gz")
        for w in next(iter(r["blocks"].values()))[:2]:
            hashes=[]
            for a in r["options"]:
                lane=host.lane()
                hist,h,state=prefix(lane,j[1]|dict(seed=w["seed"]),w["order"],j[0]%3==1)
                snap=lane.request("synthetic_snapshot")
                hashes.append(dict(action=a,continuation=digest(snap["continuation"]),snapshot=digest(snap),
                                   public=digest([hist,h])))
                lane.reset()
            assert len({v["snapshot"] for v in hashes})==1
            assert len({v["continuation"] for v in hashes})==1
            assert all(v["public"]==r["key"] for v in hashes)
            rows.append(dict(id=j[0],seed=w["seed"],hashes=hashes))
    host.close()
    write(out/"worlds.json",dict(seconds=perf_counter()-t,rows=rows))


if __name__=="__main__":
    run(Path(sys.argv[1]))
