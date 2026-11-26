"""Resume exact next-hand integration on the first four development openings."""
from collections import Counter
from pathlib import Path
import argparse
from time import perf_counter
from search import HERE,Lane,ask,cohort,host_at,integrate,policy,read,write


def mass(result):
    by_kind=Counter()
    for leaf in result["successors"]:
        by_kind[leaf["kind"]]+=leaf["probability"]
    return dict(by_kind)


def run(out,build):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host=host_at(out,build)
    jobs=[j for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"] if j["split"]=="development"]
    rows=[]
    try:
        for j in jobs[:4]:
            lane=Lane(host,0)
            try:
                st=cohort.start(lane,j["spec"])
                h=host.project(st["observation"])
                g=ask(lane,h,[],"reduced",160)
                plan=policy(g)
                early=integrate(lane,h,[],plan,8)
                later=integrate(lane,h,[],plan,120,previous=early)
                rows.append(dict(family=j["family"],mass8=mass(early),mass128=mass(later),
                            calls=later["calls"],requests=len(later["events"]),settlement=later))
            finally:
                lane.close()
    finally:
        host.close()
        write(out/"integral.json.gz",dict(rows=rows,seconds=perf_counter()-start))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("build",type=Path)
    a=p.parse_args()
    run(a.out,a.build.resolve())
