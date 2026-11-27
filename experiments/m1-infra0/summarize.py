"""Derive exclusive Python stages and independent host/RPC estimates from immutable worker receipts."""
from collections import Counter
import gzip
import json
from pathlib import Path
import statistics
import sys

def quantiles(values):
    if not values:return None
    seq=sorted(values)
    return dict(median=statistics.median(seq),p95=seq[(95*len(seq)+99)//100-1],maximum=seq[-1])

def summarize(folder):
    result=json.loads((folder/"result.json").read_bytes())
    data=[]
    panel=json.loads(Path(__file__).with_name("panel.json").read_bytes())[result["treatment"]["kind"]]
    names={i:name for name,ids in panel.items() for i in ids}
    strata={}

    for worker in sorted(folder.glob("worker-*")):
        w=json.loads((worker/"worker.json").read_bytes())
        proc=json.loads((worker/"process.json").read_bytes())
        stages=w["stages"];hosts=w["host"]
        # The Python stack's exclusive durations partition its covered spans; host clocks are nested.
        exclusive={k[:-8]:v/1e9 for k,v in stages.items() if k.endswith("/self_ns")}
        host_s=Counter()
        for h in hosts:
            for k,ticks in h["values"].items():
                if k.endswith("_ticks"):host_s[k]+=ticks/h["frequency"]
        rpc=Counter()
        for k,v in stages.items():
            if k.startswith("rpc/") and k.endswith("/ns"):rpc[k.split("/")[1]]+=v/1e9
        residual={cmd:sec-sum(host_s[cmd+"/"+x+"_ticks"] for x in ("parse","handle","serialize"))
            -sum(stages.get("rpc_json/"+d+"/"+cmd+"/ns",0)/1e9 for d in ("send","recv"))
            for cmd,sec in rpc.items()} if hosts else {}
        snapshots=w["root_cumulative"]
        boundaries=w.get("record_flushed_ns") or snapshots
        durations=[(b[1]-a[1])/1e9 for a,b in zip(boundaries,boundaries[1:])]
        rows=list(map(json.loads,gzip.open(worker/"evidence"/w["closed"]["file"])))
        valid=sum(bool(r.get("terminal")) or len(r.get("outcomes",[]))==2 and all(
            o.get("matched") and o.get("utility") is not None for o in r["outcomes"]) for r in rows)
        valid_c=sum(len(r["states"]) for r in rows if r.get("terminal"))
        for r in rows:
            group=strata.setdefault(names[r["i"]],Counter())
            group["attempts"]+=1
            if result["treatment"]["kind"]=="natural":
                group["valid"]+=int(bool(r.get("terminal")))
                group["valid_C"]+=len(r["states"]) if r.get("terminal") else 0
                group["actual_decisions"]+=r.get("actions",0)
                group["root_worker_seconds"]+=r.get("seconds",0)
                group["status/"+r["status"]]+=1
            else:
                sides=r.get("outcomes",[])
                matched=sum(o.get("utility") is not None and o.get("matched",False) for o in sides)
                group["valid"]+=int(len(sides)==2 and matched==2)
                group["matched_sides"]+=matched
                group["complete_plans"]+=len(r.get("plans",[]))
                group["skips"]+=int("skip" in r)
                group["errors"]+=int("error" in r)
        by_id={r["i"]:r for r in rows}
        steady_rows=[by_id[key] for key,_ in boundaries[1:]]
        resident_seconds=sum(durations)
        steady_count=sum(bool(r.get("terminal")) or (len(r.get("outcomes",[]))==2 and all(
            o.get("matched") and o.get("utility") is not None for o in r["outcomes"])) for r in steady_rows)
        data.append(dict(steady_records=len(steady_rows),steady_s=resident_seconds,
            steady_valid_per_worker_s=steady_count/resident_seconds if resident_seconds else None,python_exclusive_s=exclusive,worker_uncovered_s=(proc["end"]-proc["start"])/1e9-sum(exclusive.values()),
            rpc_residual_s=residual,host_nested_s=host_s,import_and_setup_s=(w["imported_ns"]-proc["start"])/1e9,
            first_record_s=(boundaries[0][1]-proc["start"])/1e9 if boundaries else None,
            resident_inter_record_s=quantiles(durations),natural_root_s=quantiles([r["seconds"] for r in rows if "seconds" in r]),
            valid_per_MiB=valid*2**20/w["closed"]["bytes"],valid_C_per_MiB=valid_c*2**20/w["closed"]["bytes"],
            python_cpu_s=w["python_cpu_ns"]/1e9,host_cpu_s=(sum(h["cpu_s"] for h in w["host_resources"]) if "host_resources" in w else sum(h["cpu_seconds"] for h in hosts) if hosts else None),
            host_processes=len(hosts),python_peak_bytes=w["python_resources"]["peak_rss"]))
    intervals=[]
    for f in folder.glob("worker-*/process.json"):
        v=json.loads(f.read_bytes());intervals.extend([(v["start"],1),(v["end"],-1)])
    active=peak=0
    for _,delta in sorted(intervals):
        active+=delta;peak=max(peak,active)
    return dict(strata=strata,peak_concurrent_workers=peak,treatment=result["treatment"],workers=data,wall_rates=result["per_wall_second"])

if __name__=="__main__":
    print(json.dumps(summarize(Path(sys.argv[1])),indent=2))
