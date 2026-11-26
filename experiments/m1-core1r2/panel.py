"""Paired frozen public roots and independent two-turn deployments. Development only."""
import argparse
from functools import lru_cache
from collections import Counter
import gzip
import json
from pathlib import Path
from time import perf_counter,process_time
import zipfile
from search import HERE,Lane,ask,cohort,execute,host_at,candidate,mass_kind,is_next_decision,policy,read,step,write,frontier_witnesses

CORE=HERE.parent/"m1-core1"


def witnesses(g):
    # Exclude all chance descendants. Arrival counts include every actual Play already spent.
    out=[]
    todo=[0]
    while todo:
        i=todo.pop()
        n=g["nodes"][i]
        if n["kind"]=="decision":
            out.append((n["joint"],n["at_call"]))
            todo.extend(e["to"] for e in n["edges"])
    return out


def quality(g,ref):
    visits=witnesses(g)
    cost=[min((c for v,c in visits if len(v)==len(p) and all(x>=y for x,y in zip(v,p))),default=None) for p in ref]
    return dict(reference=len(ref),covered=sum(c is not None for c in cost),
                calls_to_quality=max(cost,default=0) if None not in cost else None)


def brief(g):
    return dict(calls=g["calls"],forks=g["forks"],ms=g["milliseconds"],nodes=len(g["nodes"]),
        counts=g["counts"],front=g["no_draw_front"],kinds=Counter(n["kind"] for n in g["nodes"]))


def paired(lane,job,prior,oldrow,ordinal,r1):
    st=cohort.start(lane,job["spec"])
    history=[]
    rows=[]
    for i,old in enumerate(prior["graphs"]):
        h=lane.host.project(st["observation"])
        if {k:v for k,v in h.items() if k not in ("tuning_fork","order_hooks")}!=old["root"]:
            raise ValueError("Old public anchor mismatch")
        met=old["metrics"]
        work=sum(met.get(k,0) for k in ("steps","sv1_transitions","prefix_steps"))
        row=dict(turn=h["turn"],old_calls=work,old_restores=met["root_restores"],old_seconds=met["seconds"],
                 old_B=oldrow["queries"][i].get("executed")=="B")
        row["timing_order"]=["tree","reduced"] if (i+ordinal)%2==0 else ["reduced","tree"]
        graphs={}
        for mode in row["timing_order"]:
            t=perf_counter()
            g=graphs[mode]=ask(lane,h,history,mode,160)
            row[mode]=brief(g)|dict(rpc_seconds=perf_counter()-t)
        reference=graphs["tree"]["no_draw_front"]
        row["quality"]={mode:quality(g,reference) for mode,g in graphs.items()}
        row["gaps"]=[]
        for w in frontier_witnesses(graphs["tree"]):
            if quality(graphs["reduced"],[w["joint"]])["covered"]: continue
            trace=[]
            idx=0
            for action in w["route"]:
                node=graphs["tree"]["nodes"][idx]
                edge=next(e for e in node["edges"] if e["input"]["index"]==action["action"])
                card=node["state"]["hand"][edge["input"]["card"]]
                trace.append([card["id"],card["upgrade"],edge["input"]["target"]])
                idx=edge["to"]
            row["gaps"].append(dict(joint=w["joint"],witness=trace))
        row["r1"]=r1["paired"][i]["reduced"]
        row["root_law"]=st.get("public_law")
        row["effects"]=graphs["reduced"]["nodes"][0]["effects"]
        if ordinal<4 and i==0:
            deep={k:ask(lane,h,history,k,640) for k in row["timing_order"]}
            row["deep"]={k:brief(g)|quality(g,deep["tree"]["no_draw_front"]) for k,g in deep.items()}
        rows.append(row)
        if i+1<len(prior["graphs"]):
            for o,index in prior["executions"][i]["path"]:
                actual=lane.host.project(st["observation"])
                if {k:v for k,v in actual.items() if k not in ("tuning_fork","order_hooks")}!=o:
                    raise ValueError("Old witness drift")
                history.append((actual,index))
                st=step(lane,st,index)
    return rows


def deploy(lane,job):
    start=perf_counter()
    st=cohort.start(lane,job["spec"])
    history,queries,leaves=[],[],[]
    counts=Counter()
    for _ in range(24):
        if st["status"]!="active" or len(leaves)>=2: break
        h=lane.host.project(st["observation"])
        if h["decision"]["phase"]!="combat":
            # Administrative public menu only; its use is always a counted fallback.
            a=h["actions"][0]["index"]
            history.append((h,a))
            st=step(lane,st,a)
            counts["fallback_actions"]+=1
            if st["status"]=="active":
                o=lane.host.project(st["observation"])
                if is_next_decision(o,len(leaves)+1):
                    leaves.append(dict(kind="B",state=o,observed_c=st.get("observed_c"),history_length=len(history)))
            continue
        begin=perf_counter()
        g=ask(lane,h,history,"reduced",160)
        p,settlement=candidate(lane,h,history,g,model_enemy=True)
        latency=perf_counter()-begin
        before=len(history)
        st,reason=execute(lane,st,history,g,p)
        queries.append(dict(graph=g,policy=p,settlement=settlement,result=reason,position=before,query_seconds=latency,
                            observed_c=st.get("observed_c"),after_law=st.get("public_law")))
        counts[reason]+=1
        if reason=="B":
            leaves.append(dict(kind="B",state=lane.host.project(st["observation"]),observed_c=st.get("observed_c"),history_length=len(history)))
        elif reason=="witness_mismatch" or reason=="unresolved" or before==len(history):
            break
    if st["status"] in ("predicted_win","death"):
        leaves.append(dict(kind=st["status"],state=st["terminal_observation"]|dict(gold=(st.get("result") or {}).get("gold")),
                           history_length=len(history)))
    return dict(queries=queries,leaves=leaves,history=history,status=st["status"],counts=counts,seconds=perf_counter()-start)


def run(out,build,n):
    out.mkdir(parents=True,exist_ok=False)
    t,cpu=perf_counter(),process_time()
    host=host_at(out,build)
    jobs=[j for j in read(CORE/"benchmark.json")["jobs"] if j["split"]=="development"][:n]
    rows=[]
    with zipfile.ZipFile(HERE.parent/"m1-core1r/evidence/panel.zip") as archive:
        r1={r["family"]:r for r in json.loads(archive.read("panel.json"))["rows"]}
    with zipfile.ZipFile(CORE/"evidence/sampled.zip") as z:
        old={r["family"]:r for r in json.loads(z.read("core1-resident/summary.json"))["rows"]}
        for ordinal,j in enumerate(jobs):
            f=j["family"]
            p=Lane(host,0)
            row=dict(family=f,encounter=j["spec"]["encounter"],thickness=len(j["spec"]["deck"]))
            try:
                prior=json.loads(gzip.decompress(z.read("core1-resident/"+f+".json.gz")))
                row["paired"]=paired(p,j,prior,old[f],ordinal,r1[f])
            except (ValueError,RuntimeError,KeyError) as e: row["paired_error"]=str(e)
            finally: p.close()
            deployment_start=perf_counter()
            lane=Lane(host,0)
            try:
                detail=deploy(lane,j)
                write(out/(f+".json.gz"),detail)
                row["execution"]={k:v for k,v in detail.items() if k not in ("history","queries","leaves")}
                row["execution"].update(actions=len(detail["history"]),queries=len(detail["queries"]),
                    calls=sum(q["graph"]["calls"] for q in detail["queries"]),kinds=[l["kind"] for l in detail["leaves"]])
            except (ValueError,RuntimeError,KeyError) as e: row["error"]=str(e)
            finally: lane.close()
            row["deployment_wall_seconds"]=perf_counter()-deployment_start
            rows.append(row)
            print(j["spec"]["encounter"],row.get("execution",row.get("error")),row.get("paired_error",""),flush=True)
            write(out/"panel.json",dict(rows=rows,seconds=perf_counter()-t,python_cpu_seconds=process_time()-cpu))
    host.close()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("build",type=Path)
    p.add_argument("--roots",type=int,default=24)
    a=p.parse_args()
    run(a.out,a.build.resolve(),a.roots)
