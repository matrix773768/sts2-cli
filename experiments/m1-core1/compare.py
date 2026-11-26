"""Same-root deployment timing. Audit sampled CORE prefixes through terminal on native."""
from pathlib import Path
import sys
from time import perf_counter
from sampled import HERE,cohort
from design import read,runtime,prepared,step,write
from loop_battle import Lane
from native import check
from freeze import recipe


def episode(host,model,job,budget,forced,finish):
    lane=Lane(host,0)
    trace=[]
    try:
        st=cohort.start(lane,job["spec"])
        first=host.project(st["observation"])
        c=prepared(model,first,[])
        c.project=host.project
        model.budget=budget
        start=perf_counter()
        while st["status"]=="active" and st["actions"]<128:
            o=host.project(st["observation"])
            if not finish and o["turn"]>=first["turn"]+2 and o["decision"]["phase"]=="combat":
                break
            if len(trace)<len(forced):
                prior,a=forced[len(trace)]
                if prior!=o:
                    raise ValueError("CORE witness mismatch")
                c.history=model.encoder.update(c.history,o,o["actions"][a])
            else:
                a,_,_=c.act(o,lane,st["actions"])
            trace.append(dict(observation={k:v for k,v in o.items() if k!="nunchaku"},action=o["actions"][a]))
            st=step(lane,st,a)
            c.after(st)
        seconds=perf_counter()-start
        terminal=st.get("terminal_observation")
        if terminal:
            terminal=terminal|dict(gold=(st.get("result") or {}).get("gold"))
        return dict(status=st["status"],terminal=terminal,steps=trace,seconds=seconds,counts=c.counts)
    finally:
        lane.close()


def run(out,source,n=24):
    out.mkdir(parents=True,exist_ok=False)
    t=perf_counter()
    host,model=runtime(out)
    rows=[]
    try:
        jobs={j["family"]:j for j in read(HERE/"benchmark.json")["jobs"]}
        for idx,record in enumerate(read(source/"summary.json")["rows"][:n]):
            job=jobs[record["family"]]
            job=job | dict(spec=recipe(job,record.get("domain","natural"),idx))
            row=dict(family=job["family"],encounter=job["spec"]["encounter"])
            for budget in (0,24):
                try:
                    data=episode(host,model,job,budget,[],False)
                    row[str(budget)]={k:v for k,v in data.items() if k!="steps"}|dict(actions=len(data["steps"]))
                except (ValueError,RuntimeError) as e:
                    row[str(budget)]=dict(error=str(e))
            if idx<4:
                left,right=Lane(host,1),Lane(host,2)
                try:
                    executions=read(source/(job["family"]+".json.gz"))["executions"]
                    forced=[s for ex in executions for s in ex["path"]]
                    if not forced:
                        row["native"]=dict(skipped="no executed CORE prefix")
                    else:
                        ref=episode(host,model,job,0,forced,True)
                        left.open()
                        right.open()
                        native=check(left,right,[idx,job["spec"]],ref,host.runtime["targets"].project)
                        row["native"]=dict(core_steps=len(forced),total_steps=len(ref["steps"]),result=native)
                except (RuntimeError,ValueError,TypeError,KeyError,AssertionError) as e:
                    row["native"]=dict(error=repr(e))
                finally:
                    left.close()
                    right.close()
            rows.append(row)
            write(out/"compare.json",dict(rows=rows,seconds=perf_counter()-t))
    finally:
        host.close()


if __name__=="__main__":
    run(Path(sys.argv[1]),Path(sys.argv[2]))
