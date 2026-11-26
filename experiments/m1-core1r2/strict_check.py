"""Independently replay each selected public witness under strict C settlement on development only."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
from time import perf_counter
from search import HERE,Lane,binding,comparable,cohort,host_at,integrate,mass_kind,read,step,write


def run(out,panel,build):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host=host_at(out,build)
    spec=importlib.util.spec_from_file_location("historical_core1r",HERE.parent/"m1-core1r/search.py")
    old=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    jobs={j["family"]:j for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"] if j["split"]=="development"}
    rows=[]
    try:
        for item in read(panel/"panel.json")["rows"]:
            family=item["family"]
            detail=read(panel/(family+".json.gz"))
            lane=Lane(host,0)
            try:
                st=cohort.start(lane,jobs[family]["spec"])
                position=0
                for q in detail["queries"]:
                    while position<q["position"]:
                        _,index=detail["history"][position]
                        st=step(lane,st,index)
                        position+=1
                    h=host.project(st["observation"])
                    expected=host.project(q["graph"]["nodes"][0]["state"])
                    if (comparable(h)!=comparable(expected) or sorted(binding(h,a) for a in h["actions"])!=
                            sorted(binding(expected,a) for a in expected["actions"])):
                        raise ValueError("Replay diverged at public root")
                    history=detail["history"][:position]
                    result=integrate(lane,h,history,q["policy"],24)
                    mass=Counter()
                    for leaf in result["successors"]:
                        mass[mass_kind(leaf)]+=leaf["probability"]
                    rows.append(dict(family=family,position=position,mass=mass,
                        calls=result["calls"],seconds=result["rpc_seconds"],old_law=old.belief(h,history) is not None,
                        successors=result["successors"]))
            finally:
                lane.close()
    finally:
        host.close()
        write(out/"strict.json.gz",dict(rows=rows,seconds=perf_counter()-start))


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    for name in ("out","panel","build"): cli.add_argument(name,type=Path)
    args=cli.parse_args()
    run(args.out,args.panel,args.build.resolve())
