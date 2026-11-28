"""Locate the first differing fields on the sealed H3-R natural trajectories."""
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/"engine/HotSearch"))
from models import boundary_key, strategic


def diff(a,b,path=""):
    if a == b:
        return []
    if isinstance(a,dict) and isinstance(b,dict):
        return [d for k in sorted(a.keys()|b.keys()) for d in diff(a.get(k),b.get(k),path+"/"+k)]
    if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in diff(x,y,path+"/"+str(i))]
    return [[path,a,b]]


def run(run_dir="logs/hotsearch/formal-strict",output="h3-first-difference.json.gz"):
    rows=list(map(json.loads,gzip.open(ROOT/run_dir/"natural.jsonl.gz")))
    bad={r["seed"]:r for r in rows if not r["terminal"]}
    folder,=(ROOT/run_dir/"transport").iterdir()
    evidence={}
    current=None
    for cmd,result in zip(map(json.loads,(folder/"commands.jsonl").open("rb")),
            (v for v in (json.loads(line) for line in (folder/"stdout.log").open("rb") if line.startswith(b'{')) if v.get("type") in ("hot","g2"))):
        if cmd["op"]=="open":
            current=bad.get(cmd["spec"]["seed"]);support={}
            if current:
                report=evidence[current["i"]]=dict(reason=current["reason"],encounter=current["encounter"],action=current["trace"][-1])
                query=current["queries"][-1]
                report["turn"]=query["turn"]
        if not current:continue
        val=result.get("result")
        if isinstance(val,list):
            for r in val:
                for leaf in r["leaves"]:
                    obj=strategic(leaf["facts"],leaf["draw"]) if leaf["kind"]=="C" else leaf
                    k=boundary_key(leaf["kind"],obj)
                    if k in query.get("law",{}):support[k]=obj
        if isinstance(val,dict) and val.get("facts"):last=val
        if not result.get("ok",True):
            report["last_public"]=last
        if isinstance(val,dict) and val.get("observed_c") and query.get("matched")==False:
            c=val["observed_c"];obj=strategic(c["facts"],c["draw"])
            if boundary_key("C",obj)==query["observed"]:
                report["actual"]=obj
        if isinstance(val,dict) and val.get("status") in ("Victory","Defeat") and query.get("matched")==False:
            if boundary_key(val["status"],val["facts"])==query["observed"]:
                report["actual"]={"kind":val["status"],**{k:val["facts"][k] for k in ("hp","max_hp","gold")}}
        if query.get("matched")==False and len(support)==len(query["law"]) and "actual" in report:
            report["support"]=query["law"];report["predicted"]=dict(support)
            report["nearest_diff"]=min((diff(o,report["actual"]) or diff(list(o.get("belief",{}).get("counts",{})),list(report["actual"].get("belief",{}).get("counts",{})),"/belief/order") for o in support.values()),key=len)
    with gzip.open(HERE/"evidence"/output,"wt",encoding="utf8") as f:json.dump(evidence,f,separators=(",",":"))
    for i,r in evidence.items():print(i,str(r.get("nearest_diff",r["reason"]))[:430])

if __name__=="__main__":run(*sys.argv[1:])
