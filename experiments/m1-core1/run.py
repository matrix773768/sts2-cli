"""Measure complete-turn candidate generation and execute on separate held-out live lanes."""
import argparse
import ctypes
from ctypes import wintypes
from collections import Counter
from pathlib import Path
from time import perf_counter, process_time
from sampled import HERE, cohort, digest, follow, search
from design import runtime, read, write
from loop_battle import Lane
from policy import compile_policy
from freeze import recipe


class TimedLane(Lane):
    """User plus kernel CPU of this Windows host, including recycled processes."""
    cpu_seconds=0.

    def close(self):
        proc=self.client.proc if self.client else None
        super().close()
        if proc is not None:
            times=[wintypes.FILETIME() for _ in range(4)]
            if not ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(proc._handle),
                    *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError()
            self.cpu_seconds+=sum((t.dwHighDateTime<<32)+t.dwLowDateTime for t in times[2:])/1e7


def diagnostic_value(kind,state):
    if kind=="predicted_win":
        return 1000+state["hp"]
    if kind=="death":
        return -1000
    return state["hp"]-.4*sum(e["hp"] for e in state["enemies"])


def run(out,n,turns,k,domain,reuse,split):
    out.mkdir(parents=True,exist_ok=False)
    start,cpu = perf_counter(),process_time()
    host,model = runtime(out)
    real, planner = TimedLane(host,0), TimedLane(host,1)
    jobs = [j for j in read(HERE/"benchmark.json")["jobs"] if j["split"]==split][:n]
    summaries = []
    try:
        for ordinal,j in enumerate(jobs):
            spec = recipe(j,domain,ordinal)
            public_recipe={key:value for key,value in spec.items() if key!="seed"}
            history,graphs,executions = [],[],[]
            row = dict(family=j["family"],split=split,domain=domain,hp=spec["hp"],encounter=spec["encounter"],
                       deck=len(spec["deck"]),queries=[])
            try:
                st = cohort.start(real,spec)
                for turn in range(turns):
                    h = host.project(st["observation"])
                    g = search(planner,model,public_recipe,history,h,k,reuse=reuse)
                    graphs.append(g)
                    kinds = Counter(b["kind"] for p in g["policies"] for b in p["branches"])
                    tick = perf_counter()
                    plan = compile_policy(g,diagnostic_value)
                    g["metrics"]["compile_seconds"] = perf_counter()-tick
                    q = dict(metrics=g["metrics"],kinds=kinds,accepted=g["draws"],ess=g["ess"],
                             candidates=len(g["policies"]),turn=h["turn"])
                    row["queries"].append(q)
                    if plan is None or plan["coverage"] < 1.-1e-10:
                        q["stop"]="no_qualified_candidate"
                        break
                    stats = Counter()
                    path,kind,leaf = follow(real,model,st,history,h,plan,stats,{})
                    history.extend(path)
                    executions.append(dict(kind=kind,path=path,leaf=leaf,plan=plan))
                    q.update(executed=kind,execution=dict(stats))
                    if kind!="B" or turn+1==turns:
                        break
                    # Restore actual episode by its own recorded legal actions.
                    real.reset()
                    st=cohort.start(real,spec)
                    for o,a in history:
                        if host.project(st["observation"])!=o:
                            raise ValueError("Actual witness replay diverged")
                        st=cohort.step(real,st,a)
                    if host.project(st["observation"])!=leaf:
                        raise ValueError("Actual B replay diverged")
            except (ValueError,RuntimeError,KeyError,IndexError,StopIteration) as e:
                row["error"]=repr(e)
            finally:
                for lane in (real,planner):
                    lane.close()
            summaries.append(row)
            write(out/(j["family"]+".json.gz"),dict(graphs=graphs,executions=executions))
            print(spec["encounter"],[(q["accepted"],q.get("executed")) for q in row["queries"]],row.get("error",""),flush=True)
            write(out/"summary.json",dict(rows=summaries,seconds=perf_counter()-start,
                                          python_cpu_seconds=process_time()-cpu,
                                          host_cpu_seconds=real.cpu_seconds+planner.cpu_seconds,host=host.version))
    finally:
        real.close()
        planner.close()
        host.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("out",type=Path)
    parser.add_argument("--roots",type=int,default=12)
    parser.add_argument("--turns",type=int,default=2)
    parser.add_argument("--worlds",type=int,default=3)
    parser.add_argument("--domain",choices=("natural","hard","cross"),default="natural")
    parser.add_argument("--split",choices=("development","confirmation"),default="development")
    parser.add_argument("--no-reuse",action="store_true")
    args=parser.parse_args()
    run(args.out,args.roots,args.turns,args.worlds,args.domain,not args.no_reuse,args.split)
