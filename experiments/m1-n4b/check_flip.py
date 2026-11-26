"""Independent replication of the observed continuation-dependent rank change at training root 54."""
from pathlib import Path
import sys
from time import perf_counter
from design import jobs,runtime,write
from research import one


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,model=runtime(out)
    t=perf_counter()
    try:
        row=one(host.lane(),model,jobs()[54],0,16,16,[0,24],domain="flip-replication-")
        write(out/"flip.json.gz",row)
    finally:
        host.close()
        write(out/"run.json",dict(seconds=perf_counter()-t,domain="flip-replication-",selection="discovery_strict_flip"))


if __name__=="__main__":
    run(Path(sys.argv[1]))
