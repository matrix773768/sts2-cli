"""Stream eligible strict HotSearch records as JSONL. Failure evidence requires an explicit flag."""
import argparse
import json
from pathlib import Path
import sys
from experience import digest,read_rows,require,scan,sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset",type=Path)
    p.add_argument("--split",choices=("train","dev","open","bridge"),required=True)
    p.add_argument("--kind",choices=("natural","conditional","reassessment"),required=True)
    p.add_argument("--behavior");p.add_argument("--policy");p.add_argument("--family");p.add_argument("--mechanism")
    p.add_argument("--native",default="not_run")
    p.add_argument("--rejected",action="store_true")
    p.add_argument("--public-views",action="store_true",help="include every public decision and choice menu for re-encoding")
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    out=a.output.open("x",encoding="utf8",newline="\n") if a.output else sys.stdout
    inline_views=False
    if a.public_views:
        manifest=json.loads((a.dataset/"manifest.json").read_bytes())
        inline_views=manifest["schema"]=="sts2.hotsearch.paired.v2"
    if a.public_views and not inline_views:
        index=json.loads((a.dataset/"public/index.json").read_bytes())
        require(index["dataset"]==manifest["id"] and index["id"]==digest({k:v for k,v in index.items() if k!="id"}),"observation manifest mismatch")
        location={t:s["shard"] for s in manifest["shards"] for t in s["tasks"]};current=None
    try:
        for row in scan(a.dataset,split=a.split,kind=a.kind,policy_id=a.policy,family=a.family,mechanism=a.mechanism,native=a.native,eligible=not a.rejected):
            if a.behavior and row["behavior_id"]!=a.behavior:continue
            if inline_views:
                prefix=row["public_prefix"]
                segments=[dict(origin="open",world=None,steps=prefix["steps"])] if prefix else []
                case=row["trajectory"]
                for seed,sides in [(None,case.get("natural_pair",[])),*[(w["seed"],w["outcomes"]) for w in case.get("worlds",[])]]:
                    segments.extend(dict(origin="restore",world=seed,steps=side["steps"]) for side in sides)
                row["public_trajectory"]=segments
            elif a.public_views:
                name=location[row["task_id"]]
                if name!=current:
                    path=a.dataset/"public"/(name+".gz")
                    require(sha(path)==index["files"][name],"public observations changed")
                    views={v["task_id"]:v["segments"] for v in read_rows(path)};current=name
                row["public_trajectory"]=views[row["task_id"]]
            out.write(json.dumps(row,ensure_ascii=True,separators=(",",":"))+"\n")
    finally:
        if a.output:out.close()
if __name__=="__main__":main()
