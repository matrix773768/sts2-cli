"""Compare a reference-only command family; child times are nested, not additive."""
from collections import Counter
import zipfile
from common import E, OLD, RUNS, json
from results import profile, read

def metrics(meta,d):
    m=profile(meta,d)
    rpc=m["rpc"]
    stages=Counter()
    counts=Counter()
    totals=Counter()
    for cmd,r in rpc.items():
        stages.update(r["host"])
        counts.update(r["host_counts"])
        for key in ("requests","wait","python_json","residual","sent","received"):
            totals[key]+=r[key]
    p=m["prefixes"]
    tr=p.get("transport",{})
    route_count=tr.get("logical_routes",p["routes"])
    edges=tr.get("edges",p["edges"])
    hits=sum(int(k.split("/")[-1])*v for k,v in counts.items() if k.startswith("prefix_hit_length/"))
    return dict(commands=totals,host_s=stages,route_queries=route_count,route_edges=edges,
                hit_edge_lengths=hits,steps=counts["replay_action"]+counts["replay_choice"],evictions=counts["evictions"],
                batch_items=tr.get("batched_routes",0),frontiers=p.get("frontiers",{}),
                public_exports=p.get("exports",{}),
                host_gc=[sum(x[i] for x in m["host_gc"]) for i in range(3)],
                python_gc=[g["collections"] for g in m["python_gc"]])

def export():
    book=read(E/"campaign.json")
    result={}
    with zipfile.ZipFile(OLD/"evidence/formal/production-receipts.zip") as z:
        for kind,tag in (("natural","infra0b-001-natural-aggregate"),("audit","infra0b-012-audit-aggregate")):
            w=json.loads(z.read(tag+"/worker-0/worker.json"))
            result[kind+"/0B-original"]=metrics(w,OLD/"evidence")
    for t in book:
        if not t["success"] or t.get("mode")!="aggregate":continue
        d=RUNS/t["label"]/"worker-0"
        result[t["kind"]+"/"+t["variant"]]=metrics(read(d/"worker.json"),d)
    (E/"host-costs.json").write_text(json.dumps(result,indent=2))
    return result
if __name__=="__main__":export()
