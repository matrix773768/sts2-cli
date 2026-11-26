"""Collect all denominators; copy complete public evidence including failed roots."""
from collections import Counter
import gzip
import json
from pathlib import Path
import statistics
import sys
import zipfile
from sampled import HERE, digest
from policy import address, compile_policy
from run import diagnostic_value

LOGS=HERE.parents[1]/"logs"


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix==".gz" else raw)


def panel(folder,bundle):
    data=read(folder/"summary.json")
    rows=data["rows"]
    counts=Counter()
    costs=Counter()
    kinds=Counter()
    acceptance=[]
    latencies=[]
    sample_sizes=Counter()
    for row in rows:
        p=folder/(row["family"]+".json.gz")
        bundle.write(p,folder.name+"/"+p.name)
        records=read(p)
        successes=0
        for i,(g,q) in enumerate(zip(records["graphs"],row["queries"],strict=True)):
            measures=g["metrics"]
            costs.update(measures)
            k=g["draws"]
            sample_sizes[k]+=1
            counts["accepted_worlds"]+=k
            counts["queries"]+=1
            counts["candidates"]+=len(g["policies"])
            if k:
                acceptance.append(g["ess"])
            latencies.append(measures["seconds"]+measures.get("compile_seconds",0))
            choices={}
            for pol in g["policies"]:
                for b in pol["branches"]:
                    kinds[b["kind"]]+=1
                    prefix=[]
                    for key,a in b["witness"]:
                        node=address(prefix,key)
                        menu,expanded=choices.setdefault(node,(g["observations"][key]["actions"],set()))
                        expanded.add(a)
                        prefix.append((key,a))
            counts["legal_info_actions"]+=sum(len(m) for m,_ in choices.values())
            counts["visited_info_actions"]+=sum(len(s) for _,s in choices.values())
            if "executed" not in q:
                counts[q.get("stop","other_stop")]+=1
                continue
            ex=records["executions"][i]
            plan=ex["plan"]
            recalculated=compile_policy(g,diagnostic_value)
            assert recalculated["rules"]==plan["rules"]
            counts["executed_"+ex["kind"]]+=1
            counts["deployment_actions"]+=len(ex["path"])
            counts["deployment_inferences"]+=q["execution"].get("inferences",0)
            prefix=[]
            for o,a in ex["path"]:
                key=digest(o)
                rule=plan["rules"].get(address(prefix,key))
                if rule is None:
                    counts["unseen_menu_actions"]+=1
                elif rule!=a:
                    raise ValueError("Execution violates guarded policy")
                prefix.append((key,a))
            if any(b["kind"]==ex["kind"] and b["state"]==ex["leaf"] for b in recalculated["successors"]):
                counts["actual_leaf_in_sample"]+=1
            successes+=int(ex["kind"] in ("B","death","predicted_win"))
        counts["roots_with_completion"]+=int(successes>0)
        counts["two_successive"]+=int(successes==2)
    bundle.write(folder/"summary.json",folder.name+"/summary.json")
    return dict(roots=len(rows),families=len({r["family"] for r in rows}),encounters=len({r["encounter"] for r in rows}),
                thickness=[min(r["deck"] for r in rows),max(r["deck"] for r in rows)],
                seconds=data["seconds"],python_cpu_seconds=data["python_cpu_seconds"],
                host_cpu_seconds=data.get("host_cpu_seconds"),counts=counts,kinds=kinds,
                accepted_histogram=sample_sizes,ess_min=min(acceptance,default=None),
                query_seconds_median=statistics.median(latencies),query_seconds_max=max(latencies),work=costs)


def archive(out):
    out.mkdir(exist_ok=True)
    result={}
    with zipfile.ZipFile(out/"sampled.zip","x",compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ("resident","pressure","transfer","world8"):
            result[name]=panel(LOGS/("core1-"+name),bundle)
    (out/"summary.json").write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":
    archive(Path(sys.argv[1]))
