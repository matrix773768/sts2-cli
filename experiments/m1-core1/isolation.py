"""Paired differential on independent private donors matching the same public root."""
from collections import Counter
from pathlib import Path
import sys
from time import perf_counter
from sampled import HERE,card_type,cohort,digest,opening,search,worlds
from design import read,runtime,write
from loop_battle import Lane


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host,m=runtime(out)
    lane=Lane(host,0)
    spec=read(HERE/"benchmark.json")["jobs"][2]["spec"]
    try:
        st=cohort.start(lane,spec)
        h=host.project(st["observation"])
        lane.reset()
        recipe=spec|dict(deck=sorted(spec["deck"],key=card_type))
        work=Counter()
        donors=worlds(lane,recipe,[],h,2,96,work)
        assert len(donors)==2 and donors[0][0]!=donors[1][0]
        signatures=[]
        stats=[]
        for n,(w,_) in enumerate(donors):
            st=opening(lane,recipe,w,[],work)
            o=host.project(st["observation"])
            assert o==h
            lane.reset()
            # Neither physical order nor donor seed is an argument to policy scoring.
            alternate=recipe|dict(seed=w[0],deck=list(reversed(recipe["deck"])) if n else recipe["deck"])
            graph=search(lane,m,alternate,[],o,reuse=bool(n))
            stats.append(graph.pop("metrics"))
            signatures.append(digest(graph))
        assert len(set(signatures))==1
        write(out/"isolation.json",dict(graph_hashes=signatures,metrics=stats,donor_metrics=work,
              distinct_donor_orders=donors[0][0][1]!=donors[1][0][1],seconds=perf_counter()-start))
    finally:
        lane.close()
        host.close()


if __name__=="__main__":
    run(Path(sys.argv[1]))
