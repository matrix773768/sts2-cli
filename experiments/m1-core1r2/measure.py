"""Recompute CORE-1R2 acceptance from per-root graphs, executor observations and historical pairings."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil
import zipfile
from statistics import median
from time import perf_counter


def load(path):
    data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix==".gz" else data)


def metrics(panel,details):
    rows=panel["rows"]
    pairs=[q for r in rows for q in r.get("paired",[])]
    qs=[q for d in details for q in d["queries"]]
    modes=("tree","r1","reduced")
    finished=[q for q in pairs if set(q["tree"]["kinds"])<= {"decision","victory","death"}
              and not q["tree"]["counts"].get("depth_cap")]
    both=[q for q in pairs if q["quality"]["reduced"]["calls_to_quality"] is not None]
    mass=Counter()
    audit=Counter()
    different=Counter()
    chosen=Counter()
    selected_candidates=Counter()
    root_laws=Counter()
    for q in qs:
        s=q["settlement"]
        m=s["candidates"][s["selected"]]["mass"]
        mass.update(m)
        chosen.update([s["selected"]])
        selected_candidates.update([len(s["candidates"])])
        law=q["graph"]["nodes"][0]["belief"]
        root_laws["partial" if law.get("membership_gap") or law.get("order_gap") else "available"]+=1
        actual=q.get("observed_c")
        if not actual or len(s["successors"])!=1: continue
        leaf=s["successors"][0]
        if leaf["kind"]!="C": continue
        tag="proxy" if leaf["approximate"] else "rules"
        predicted=leaf["state"]
        fields=(predicted.keys()|actual.keys())-{"events","enemy_models"}
        differences=[k for k in fields if predicted.get(k)!=actual.get(k)]
        audit[tag+"_compared"]+=1
        audit[tag+"_matched"]+=not differences
        for k in differences:different[tag+"_"+k]+=1
    totals=lambda items,key:{m:sum(q[m][key] for q in items) for m in modes}
    root_effects=[e for q in pairs for e in q["effects"]]
    old_roles={"STRIKE_IRONCLAD","STRIKE_SILENT","DEFEND_IRONCLAD","DEFEND_SILENT","BASH","TRIP","INFLAME","FLEX","FOOTWORK"}
    all_counts=sum((Counter(q["reduced"]["counts"]) for q in pairs),Counter())
    deeper=[q["deep"] for q in pairs if "deep" in q]
    historical_front=sum(any(len(v)==len(t) and all(x>=y for x,y in zip(v,t))
        for v in q["r1"]["front"]) for q in pairs for t in q["tree"]["front"])
    c_sizes=[len(json.dumps(q["observed_c"],separators=(",",":")).encode()) for q in qs if q.get("observed_c")]
    return dict(observed_c_json_bytes=[min(c_sizes),median(c_sizes),max(c_sizes)],
        historical_front_covered=historical_front,families=len(rows),errors=[(r["family"],r.get("paired_error"),r.get("error"))
          for r in rows if "paired_error" in r or "error" in r],paired_anchors=len(pairs),
        encounters=len({r["encounter"] for r in rows}),deck_range=[min(r["thickness"] for r in rows),max(r["thickness"] for r in rows)],
        calls=totals(pairs,"calls"),nodes=totals(pairs,"nodes"),rpc_seconds=totals(pairs,"rpc_seconds"),
        complete_deterministic_roots=len(finished),complete_calls=totals(finished,"calls"),
        complete_front_covered=sum(q["quality"]["reduced"]["calls_to_quality"] is not None for q in finished),
        equal_quality_roots=len(both),calls_to_quality={m:sum(q["quality"][m]["calls_to_quality"] for q in both) for m in ("tree","reduced")},
        target_points=sum(q["quality"]["tree"]["reference"] for q in pairs),
        covered_points=sum(q["quality"]["reduced"]["covered"] for q in pairs),
        gaps=[dict(family=r["family"],turn=q["turn"],gaps=q["gaps"]) for r in rows for q in r.get("paired",[]) if q["gaps"]],
        deeper=dict(calls={m:sum(d[m]["calls"] for d in deeper) for m in ("tree","reduced")},roots=len(deeper),target=sum(d["tree"]["reference"] for d in deeper),covered=sum(d["reduced"]["covered"] for d in deeper)),
        root_candidates=len(root_effects),root_classified=sum(e["role"]!="special" for e in root_effects),
        old_root_classified=sum(e["card"] in old_roles for e in root_effects),counts=all_counts,modeled_mass_per_query={k:v/len(qs) for k,v in sorted(mass.items())},
        two_B=sum(sum(l["kind"]=="B" for l in d["leaves"])==2 for d in details),
        observed_C=sum(l.get("observed_c") is not None for d in details for l in d["leaves"]),
        selected=chosen,candidates=selected_candidates,root_laws=root_laws,audit=audit,differences=different,
        deployment=dict(queries=len(qs),actions=sum(len(d["history"]) for d in details),
            counts=sum((Counter(d["counts"]) for d in details),Counter()),
            administrative_steps=sum(o["decision"]["phase"]!="combat" for d in details for o,a in d["history"]),
            search_calls=sum(q["graph"]["calls"] for q in qs),settlement_calls=sum(q["settlement"]["all_calls"] for q in qs),
            prefix_replays=sum(q["settlement"]["root_replays"] for q in qs),
            settlement_rpc_seconds=sum(q["settlement"]["all_rpc_seconds"] for q in qs),
            query_ms_median=median(q["query_seconds"] for q in qs)*1000,
            wall_seconds=sum(r["deployment_wall_seconds"] for r in rows)),panel_seconds=panel["seconds"],python_cpu_seconds=panel["python_cpu_seconds"])


def archive(out,panel,fixtures,native,build,strict):
    out.mkdir(parents=True,exist_ok=False)
    p=load(panel/"panel.json")
    files=[panel/(r["family"]+".json.gz") for r in p["rows"] if "execution" in r]
    details=[load(f) for f in files]
    summary=metrics(p,details)
    from search import rule_context
    states=[q["observed_c"] for d in details for q in d["queries"] if q.get("observed_c")]
    start=perf_counter()
    contexts=[rule_context(c) for c in states]
    first_seconds=perf_counter()-start
    start=perf_counter()
    for _ in range(25):
        for c in states: rule_context(c)
    features=dict(states=len(states),cold_batch_seconds=first_seconds,
                  warm_joins=25*len(states),warm_batch_seconds=perf_counter()-start)
    for group in ("cards","graphs"):
        entities={k:v is not None for ctx in contexts for k,v in ctx[group].items()}
        features[group]=dict(distinct=len(entities),missing=sorted(k for k,found in entities.items() if not found))
    (out/"features.json").write_text(json.dumps(features,indent=2)+"\n",encoding="utf8")
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf8")
    with zipfile.ZipFile(out/"panel.zip","x",compression=zipfile.ZIP_DEFLATED) as z:
        for f in [panel/"panel.json",*files]:z.write(f,arcname=f.name)
    for f in (fixtures/"fixtures.json.gz",native/"native.json",build/"build.json",strict/"strict.json.gz"):
        shutil.copyfile(f,out/f.name)
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("out","panel","fixtures","native","build","strict"): parser.add_argument(name,type=Path)
    archive(**vars(parser.parse_args()))
