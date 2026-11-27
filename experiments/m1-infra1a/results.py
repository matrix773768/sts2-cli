"""Export observed rates, logical production work, physical transport and raw receipts."""
from collections import Counter
from statistics import mean
import gzip
import zipfile
from common import HERE, ROOT, OLD, RUNS, E, entries, json, sha
from reuse_results import export as shadow_export

def read(p):
    return json.loads(p.read_bytes())

def profile(meta,folder):
    h=Counter(); seconds=Counter()
    ss=meta["stages"]
    for sample in meta["host"]:
        for k,v in sample["values"].items():
            if k.endswith("_ticks"):seconds[k]+=v/sample["frequency"]
            else:h[k]+=v
    rpc={}
    for cmd in ["i1_core5_reference","i1_infra1_reference_batch"]:
        wait=ss.get("rpc/"+cmd+"/ns",0)/1e9
        if not wait:continue
        py=sum(ss.get(f"rpc_json/{d}/{cmd}/ns",0) for d in ("send","recv"))/1e9
        stages={k.split("/",1)[1]:v for k,v in seconds.items() if k.startswith(cmd+"/")}
        core=[stages.get(k,0) for k in ("handle_ticks","serialize_ticks","parse_ticks")]
        rpc[cmd]=dict(requests=h[cmd+"/requests"],wait=wait,python_json=py,host=stages,
            residual=wait-py-sum(core),sent=ss.get("bytes_sent/"+cmd),received=ss.get("bytes_received/"+cmd),
            host_counts={k.split("/",1)[1]:v for k,v in h.items() if k.startswith(cmd+"/")})
    prefixes={int(k.rsplit("/",1)[1]):v for k,v in ss.items() if k.startswith("rpc/i1_core5_reference/prefix/")}
    logical=dict(routes=sum(prefixes.values()),edges=sum(k*v for k,v in prefixes.items()))
    metrics=folder/"batch-metrics.json"
    if metrics.exists():logical.update(read(metrics))
    return dict(rpc=rpc,prefixes=logical,python_gc=meta["gc"],host_gc=[v["gc"] for v in meta["host"]])

def export():
    book=entries()
    rows=[]
    with zipfile.ZipFile(E/"production.zip","w",compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for entry in book:
            tag=entry["label"]
            if not tag.startswith("infra1a-"):continue
            folder=RUNS/tag
            for p in list(folder.glob("*.json"))+list(folder.glob("worker-*/*.json"))+list(folder.glob("worker-*/shadow.json.gz"))+list(folder.glob("worker-*/evidence/*.gz")):
                if p.name!="panel.gz":z.write(p,p.relative_to(RUNS))
            if not (folder/"result.json").exists():continue
            res=read(folder/"result.json")
            w=folder/"worker-0"
            meta=read(w/"worker.json")
            table=entry|dict(python_cpu=meta["python_cpu_ns"]/1e9,host_cpu=sum(h["cpu_s"] for h in meta["host_resources"]),
                python_rss=meta["python_resources"]["peak_rss"],host_rss=max(h["peak_rss"] for h in meta["host_resources"]),
                compressed=meta["closed"]["bytes"],threads=meta["threads"],interop=meta["interop"],rates=res["per_wall_second"])
            if meta["stages"]:table["profile"]=profile(meta,w)
            if (w/"g2-check.json").exists():table["g2"]=read(w/"g2-check.json")
            rows.append(table)
    (E/"campaign.json").write_text(json.dumps(book,indent=2))
    (E/"treatments.json").write_text(json.dumps(rows,indent=2))
    comparisons={}
    for kind in {r.get("kind") for r in rows if r.get("phase","").startswith("cross")}:
        group=[r for r in rows if r.get("kind")==kind and r.get("phase","").startswith("cross") and r["success"]]
        by={v:[r for r in group if r["variant"]==v] for v in ("original","batch")}
        if not all(by.values()):continue
        avg={v:mean(r["wall"] for r in items) for v,items in by.items()}
        total=group[0]["totals"]
        comparisons[kind]=dict(walls={v:[r["wall"] for r in items] for v,items in by.items()},
            speedup=avg["original"]/avg["batch"],means=avg,totals=total,
            rates={v:{k:n/avg[v] for k,n in total.items()} for v in avg},
            memory={v:[max(r[m] for r in items)/2**20 for m in ("python_rss","host_rss")] for v,items in by.items()})
    (E/"comparisons.json").write_text(json.dumps(comparisons,indent=2))
    manifests={}
    for p in sorted((ROOT/"logs").glob("infra1a-5*")):
        if (p/"build.json").exists():
            h=read(p/"build.json")
            assert all(sha(p/k)==v for k,v in h["artifacts"].items())
            manifests[p.name]=dict(artifacts=h["artifacts"],parent=h["infra_parent"])
    (E/"hosts.json").write_text(json.dumps(manifests,indent=2))
    inherited=read(OLD/"evidence/formal/deployment.json")
    inputs=dict(frozen_infra="6651a4ec14220abb581194240476c490c557b24d",core5d=inherited["core5d"],
                core5e=inherited["core5e"],runtime=inherited["runtime_sha256"],
                panel={n:sha(OLD/n) for n in ("panel.json","world-panel.json")})
    (E/"inputs.json").write_text(json.dumps(inputs,indent=2))
    shadow_export()
    return comparisons
if __name__=="__main__":export()
