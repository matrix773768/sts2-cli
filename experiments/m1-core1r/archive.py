"""Package verified research outputs and recompute the paired metrics from raw rows."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from statistics import median
import zipfile


def load(path):
    with (gzip.open(path,"rt",encoding="utf8") if path.suffix==".gz" else path.open(encoding="utf8")) as file:
        return json.load(file)


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


def paired_metrics(rows):
    def front(q,mode):
        return set(map(tuple,q[mode]["front"]))
    comparisons=[q for r in rows for q in r.get("paired",[])]
    result=dict(anchors=len(comparisons),old_calls=sum(q["old_calls"] for q in comparisons),
                old_restores=sum(q["old_restores"] for q in comparisons),
                old_seconds=sum(q["old_seconds"] for q in comparisons))
    for mode in ("tree","reduced","old_budget"):
        data=[q[mode] for q in comparisons if mode in q]
        result[mode]=dict(queries=len(data),calls=sum(x["calls"] for x in data),
            forks=sum(x["forks"] for x in data),nodes=sum(x["nodes"] for x in data),
            simulator_seconds=sum(x["ms"] for x in data)/1000,
            rpc_seconds=sum(x.get("rpc_seconds",0) for x in data) if mode!="old_budget" else None,
            stops=sum(x["counts"].get("budget",0) for x in data),
            decisions=sum(x["kinds"].get("decision",0) for x in data),
            other_stops=dict(sum((Counter(x["kinds"]) for x in data),Counter())))
    result["old_positive_anchor_calls"]=sum(q["old_calls"] for q in comparisons if "old_budget" in q)
    result["distinct_tree_vectors"]=sum(len(front(q,"tree")) for q in comparisons)
    result["distinct_reduced_vectors"]=sum(len(front(q,"reduced")) for q in comparisons)
    result["identical_fronts"]=sum(front(q,"reduced")==front(q,"tree") for q in comparisons)
    result["matched_vectors"]=sum(len(front(q,"tree") & front(q,"reduced")) for q in comparisons)
    result["covered_tree_vectors"]=sum(any(all(x>=y for x,y in zip(a,b)) for a in front(q,"reduced"))
            for q in comparisons for b in front(q,"tree"))
    result["reduction_events"]=dict(sum((Counter(q["reduced"]["counts"]) for q in comparisons),Counter()))
    return result


def metrics(panel,details):
    rows=panel["rows"]
    queries=[q for d in details for q in d["queries"]]
    counts=sum((Counter(d["counts"]) for d in details),Counter())
    observations=Counter(l["kind"] for d in details for l in d["leaves"])
    mass=Counter()
    reasons=Counter()
    for q in queries:
        for leaf in q["settlement"]["successors"]:
            mass[leaf["kind"]]+=leaf["probability"]
            if leaf.get("reason"): reasons[leaf["reason"]]+=leaf["probability"]
    return dict(families=len(rows),encounters=len(set(r["encounter"] for r in rows)),
        thickness=[min(r["thickness"] for r in rows),max(r["thickness"] for r in rows)],
        paired=paired_metrics(rows),panel_seconds=panel["seconds"],paired_or_exec_errors=[
            r["family"] for r in rows if "error" in r or "paired_error" in r],
        deployment=dict(seconds=sum(d["seconds"] for d in details),
            end_to_end_seconds=sum(r["deployment_wall_seconds"] for r in rows),
            actions=sum(len(d["history"]) for d in details),queries=len(queries),counts=counts,leaves=observations,
            finished_twice=sum(len(d["leaves"])>=2 for d in details),
            without_fallback_twice=sum(len(d["leaves"])>=2 and not d["counts"].get("fallback_actions") for d in details),
            query_seconds=sum(q["query_seconds"] for q in queries),
            median_query_seconds=median(q["query_seconds"] for q in queries),
            calls=sum(q["graph"]["calls"] for q in queries),forks=sum(q["graph"]["forks"] for q in queries),
            settlement_root_replays=sum(len(q["settlement"]["events"]) for q in queries),
            settlement_calls=sum(q["settlement"]["calls"] for q in queries),
            resolved_mass_per_query={k:v/len(queries) for k,v in sorted(mass.items())},
            unresolved_reason_mass_per_query={k:v/len(queries) for k,v in sorted(reasons.items())},
            complete_before_integration=sum(q["policy"]["modeled_complete_mass"] for q in queries)/len(queries),
            fully_integrated=sum(all(l["kind"] in ("B","death","victory") for l in q["settlement"]["successors"]) for q in queries),
            only_end_turn=sum(all(o["actions"][a]["kind"]=="end_turn" for o,a in d["history"]) for d in details)))


def archive(out,fixtures,panel,native,build,integral):
    out.mkdir(parents=True,exist_ok=False)
    raw=load(panel/"panel.json")
    files=[panel/(r["family"]+".json.gz") for r in raw["rows"] if "execution" in r]
    summary=metrics(raw,[load(f) for f in files])
    save(out/"summary.json",summary)
    save(out/"native.json",load(native/"native.json"))
    save(out/"build.json",load(build/"build.json"))
    (out/"integral.json.gz").write_bytes((integral/"integral.json.gz").read_bytes())
    (out/"fixtures.json.gz").write_bytes((fixtures/"fixtures.json.gz").read_bytes())
    with zipfile.ZipFile(out/"panel.zip","x",compression=zipfile.ZIP_DEFLATED) as z:
        for f in [panel/"panel.json",*files]: z.write(f,arcname=f.name)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("out","fixtures","panel","native","build","integral"):
        p.add_argument(key,type=Path)
    a=p.parse_args()
    archive(**vars(a))
