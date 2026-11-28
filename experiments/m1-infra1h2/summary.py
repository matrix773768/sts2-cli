"""Compute panel denominators, first-failure locations, original cost weights and paired production observations."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]; E=HERE/"evidence"
def read(p):return json.loads(p.read_bytes())
def archived(kind):
    w=ROOT/f"logs/infra0-runs/infra1h-A-{kind}-h-batch/worker-0"
    m=read(w/"worker.json")
    with gzip.open(w/"evidence"/m["closed"]["file"]) as f:return list(map(json.loads,f)),m
def run():
    rows,_=archived("natural")
    private=read(E/"private.json")
    a=Counter(r["stage"] for r in private)
    steps=sum(r["steps"]-(r["stage"]!="terminal") for r in private if r["stage"] in ("stop","terminal","error"))
    turns=read(E/"turns.json")
    qualified={int(t["panel"]) for t in turns if t["panel"]!="starter" and t.get("planner_delta")==[] and t.get("graph_delta")==[]}
    queries=[q for r in rows for q in r["queries"]]
    covered=[q for r in rows if r["i"] in qualified for q in r["queries"] if q["turn"]==1]
    frontier=read(ROOT/"logs/infra0-runs/infra1h-attribution-natural-h-batch/worker-0/batch-metrics.json")["frontiers"]
    states=read(E/"branches.json")
    audit,m=archived("audit");cost=dict(m["record_flushed_ns"])
    pos=[r["i"] for r in audit].index(123)
    high=audit[pos];later=list(high["states"].values())
    summary=dict(private_counts=dict(a),matched_actions=steps,
        total_actions=sum(r["actions"] for r in rows),panel_turns=len(queries),full_hot_turns=len(covered),
        panel_calls=sum(q["calls"] for q in queries),qualified_calls=sum(q["calls"] for q in covered),
        reference_replies=sum(int(size)*n for size,n in frontier.items()),policy_requests=sum(q["policy_requests"] for q in queries),
        policy_calls=sum(q["policy_calls"] for q in queries),settlements=sum(q["settles"] for q in queries),
        direct_edges=Counter(r.get("kind","stop") for r in states["edges"]),exact_edges=sum(r.get("equal",False) for r in states["edges"]),
        first_draw_children=sum(len(r.get("children",[])) for r in states["edges"]),
        child_differences=[dict(ordinal=r["ordinal"],child=c) for r in states["edges"] for c in r.get("children",[]) if c["delta"]],
        root123=dict(source=high["source"],index=high["index"],turn=high["turn"],worlds=high["world_count"],
            cost_seconds=(cost[123]-cost[audit[pos-1]["i"]])/1e9,predecessor_count=len(high["law"]["counts"]),
            visible_species=sorted({e["species"] for s in later for e in s["enemies"]}),
            visible_powers=sorted({p["id"] for s in later for p in s["powers"]+[p for e in s["enemies"] for p in e["powers"]]}),
            options=[x["label"] for x in high["plans"]],unique_C=len(later)))
    production=[]
    for f in sorted(E.glob("*.json")):
        if f.name.startswith(("natural-","audit-")):
            x=read(f);attempts=x["hot_turns"]
            production.append(dict(run=f.stem,ids=x["ids"],seconds=x["production_wall"],cleanup=x["process_wall"]-x["production_wall"],
                python_cpu=x["python_cpu"],host_cpu=sum(r["cpu_s"] for r in x["host_resources"]),archive_delta=x["archive_differences"],
                valid=x["terminal"] if x["kind"]=="natural" else sum(p["valid"] for p in x["admissions"]),
                queries=x["queries"],hot=sum(a.get("committed",False) for a in attempts),
                fallback=Counter(r.get("reason","failed_before_fallback") for r in attempts if not r.get("committed"))))
    census_file=E/"natural-census.json"
    if census_file.exists():
        census=read(census_file);queries=census["hot_turns"]
        stats={}
        for row in queries:
            name="Hot" if row.get("committed") else row.get("reason","error")
            bucket=stats.setdefault(name,dict(turns=0,search_seconds=0.,logical_calls=0,root_ids=set()))
            bucket["turns"]+=1
            bucket["search_seconds"]+=row.get("seconds",row.get("fallback_seconds",0.)+row.get("attempt_seconds",0.))
            bucket["logical_calls"]+=row.get("logical_calls",0)
            bucket["root_ids"].add(next(r["i"] for r in rows if r["seed"]==row["seed"]))
        for bucket in stats.values():bucket["root_ids"]=sorted(bucket["root_ids"])
        summary["census"]=stats
    summary["production"]=production
    (E/"summary.json").write_text(json.dumps(summary,indent=2))
    identities={}
    for name in ("5d","5d-batch","5e-batch"):
        folder=ROOT/"logs/infra1h2"/name
        manifest=read(folder/"build.json")
        identities[name]=dict(host=manifest["artifacts"],hot=manifest["hot_artifacts"],
            source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (folder/"plugin").glob("*.cs")})
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.suffix in (".py",".cs")}
    (E/"builds.json").write_text(json.dumps(dict(baseline="ee1c1d6896b00b39912982912633d07602bf9d53",
        solver="131d10ae4499b56332787af61fe4a9306e65860f",hosts=identities,sources=source),indent=2))
    ledger=[json.loads(l) for l in (ROOT/"logs/infra1h2/ledger.jsonl").read_text().splitlines()]
    (E/"ledger.json").write_text(json.dumps(dict(worker_seconds=sum(r["seconds"] for r in ledger),attempts=ledger),indent=2))
if __name__=="__main__":run()
