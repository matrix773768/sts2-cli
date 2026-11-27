"""Summarize whole, valid duplicate groups and attribute each saved query to one prior call."""
from collections import Counter, OrderedDict, defaultdict
import gzip
from common import E, RUNS, json, entries

def summary(rows,key,capacity=None):
    groups=defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    unsafe={k for k,g in groups.items() if any("error" in r for r in g) or
            any(r["output"]!=g[0]["output"] for r in g)}
    seen=OrderedDict()
    counts=Counter()
    seconds=Counter()
    peak_bytes=current_bytes=0
    for r in rows:
        k=r[key]
        if k in seen:
            prev=seen.pop(k)
            current_bytes-=prev.get("bytes_policy",0)
            root,world,side=r["location"]
            p_root,p_world,p_side=prev["location"]
            relation=("cross_root" if p_root!=root else "cross_world" if world!=p_world else
                      "different_side" if side!=p_side else "same_side")
            counts["all_hits"]+=1
            if k not in unsafe:
                counts[relation]+=1
                seconds[relation]+=r["elapsed_ns"]/1e9
        seen[k]=r
        current_bytes+=r.get("bytes_policy",0)
        if capacity and len(seen)>capacity:
            _,old=seen.popitem(last=False)
            current_bytes-=old.get("bytes_policy",0)
        peak_bytes=max(current_bytes,peak_bytes)
    differences=[]
    for k in unsafe:
        g=[r for r in groups[k] if "output" in r]
        if len(g)<2:continue
        for r in g[1:]:
            if r["output"]!=g[0]["output"]:
                differences.append(dict(key=k,first=g[0]["location"],other=r["location"],
                   fields=[f for f,v in r["output"].items() if g[0]["output"][f]!=v],
                   scalar_changes={f:[g[0]["query"].get(f),v] for f,v in r["query"].items() if g[0]["query"].get(f)!=v}))
    return dict(calls=len(rows), planner_seconds=sum(r["elapsed_ns"] for r in rows)/1e9,
                failed_calls=sum("error" in r for r in rows), unique=len(groups),
                hits=counts["all_hits"],consistent_hits=sum(counts.values())-counts["all_hits"],
                counts=counts,seconds=seconds,saved_s=sum(seconds.values()),peak_policy_bytes=peak_bytes,
                conflict_groups=len({r["key"] for r in differences}),differences=differences)

def export():
    report={}
    pooled=[]
    for entry in entries():
        if not entry["success"] or entry.get("variant")!="shadow":continue
        d=json.load(gzip.open(RUNS/entry["label"]/"worker-0/shadow.json.gz")); rows=d["rows"]
        panel_ids=json.loads((RUNS/entry["label"]/"worker-0/task.json").read_bytes())["ids"]
        suffix=[r for r in rows if r["location"][1] is not None]
        for r in suffix:
            root,world,side=r["location"]
            pooled.append(r|dict(location=[f"{entry['kind']}/{root}",world,side]))
        stats=summary(suffix,"key")
        stats["share_wall"]=stats["saved_s"]/entry["wall"]
        report[entry["kind"]]=dict(wall=entry["wall"],all_planner_calls=len(rows),suffix=stats,
            all_calls=summary(rows,"key"),coarse=summary(suffix,"coarse"),
            per_root={i:summary([r for r in suffix if r["location"][0]==i],"key") for i in panel_ids},
            lru_saved={n:summary(suffix,"key",n)["saved_s"] for n in (8,32,128,512)},
            error_calls=sum("error" in r for r in rows),planner_s=sum(r["elapsed_ns"] for r in rows)/1e9,
            key_s=sum(r["key_ns"] for r in rows)/1e9,binding_s=d["binding_ns"]/1e9)
    (E/"shadow-pooled.json").write_text(json.dumps(dict(strict=summary(pooled,"key"),coarse=summary(pooled,"coarse")),indent=2))
    (E/"shadow-summary.json").write_text(json.dumps(report,indent=2))
    return report
if __name__=="__main__":
    for kind,r in export().items():
        print(kind,r["suffix"]["hits"],r["suffix"]["consistent_hits"],r["suffix"]["saved_s"],r["suffix"]["conflict_groups"])
