"""Export the CORE primary natural dataset with one-based frozen family ranks."""
import argparse
import json
import sys
from pathlib import Path
from panel import HERE
from experience import digest,read_rows,require,sha

def export(out,public_views):
    release=json.loads((HERE/"release.json").read_bytes())
    require(digest({k:v for k,v in release.items() if k!="id"})==release["id"],"release hash")
    require(sha(HERE/"splits.json")==release["artifacts"]["splits.json"],"rank hash")
    families=json.loads((HERE/"splits.json").read_bytes())["primary_train"]
    ranks={f:i+1 for i,f in enumerate(families)}
    seen=set()
    h5=HERE.parent/"m1-infra1h5"
    parent=json.loads((h5/"release.json").read_bytes())
    require(parent["id"]=="188cda5924b614b6399810c7aad897dafb319de0c66fdb956344e9380bb1a6da" and digest({k:v for k,v in parent.items() if k!="id"})==parent["id"],"H5 release")
    old=[(h5/r["path"],r) for r in parent["editions"]]
    new=[(HERE/k,v) for k,v in release["editions"].items() if k=="train" or k.startswith("reserve-")]
    for data,ref in old+new:
        m=json.loads((data/"manifest.json").read_bytes())
        require(digest({k:v for k,v in m.items() if k!="id"})==m["id"]==ref["manifest"],"manifest")
        if public_views:
            idx=json.loads((data/"public/index.json").read_bytes())
            require(digest({k:v for k,v in idx.items() if k!="id"})==idx["id"]==ref["public"] and idx["dataset"]==m["id"],"public manifest")
        for s in m["shards"]:
            if (s["split"],s["kind"])!=("train","natural"):continue
            p=data/s["file"]
            require(sha(p)==s["sha256"],"shard hash")
            if public_views:
                p2=data/"public"/(s["shard"]+".gz")
                require(sha(p2)==idx["files"][s["shard"]],"public shard hash")
                views={v["task_id"]:v["segments"] for v in read_rows(p2)}
            for row in read_rows(p):
                f=row["family"]
                if not row["eligible"] or f not in ranks:continue
                require(f not in seen and row["native_audit"]=="not_run","duplicate or wrong audit")
                seen.add(f)
                row["primary_rank"]=ranks[f]
                if public_views:row["public_trajectory"]=views[row["task_id"]]
                out.write(json.dumps(row,separators=(",",":"))+"\n")
    require(seen==ranks.keys(),"missing primary family")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--public-views",action="store_true")
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    if a.output:
        with a.output.open("x",encoding="utf8",newline="\n") as out:export(out,a.public_views)
    else:export(sys.stdout,a.public_views)
