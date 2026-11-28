"""Recover full expected and actual public views for the failed preregistered open trajectories."""
import gzip
import json
import os
from pathlib import Path
import sys
from diagnose import HERE,ROOT,diff
from hot_produce import run
from release import pack,rows

def audit(name="open-hot"):
    base=ROOT/"logs/hotsearch-h4"
    out=base/("open-differences" if name=="open-hot" else name+"-differences")
    out.mkdir(exist_ok=False)
    views=out/"views";views.mkdir()
    os.environ["HOTSEARCH_VIEWS"]=str(views)
    specs=(json.loads((HERE/"evidence/open-specs.json").read_bytes()) if name=="open-hot" else
           json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"])
    source=base/name
    ledger=json.loads((source/"ledger.json").read_bytes())
    bad=[r for r in rows(source/"natural.jsonl.gz") if not r["terminal"]]
    subset=out/"specs.json";subset.write_text(json.dumps([specs[r["i"]] for r in bad]))
    run(out/"replay",[],ledger["arm"],ledger["limit"],subset)
    findings=[]
    for old,r in zip(bad,rows(out/"replay/natural.jsonl.gz")):
        if (r["seed"],r["reason"],r["trace"],r.get("policy_failure"))!=(old["seed"],old["reason"],old["trace"],old.get("policy_failure")):
            raise ValueError("open failure replay changed")
        item=dict(i=old["i"],encounter=r["encounter"],reason=r["reason"],trace=r["trace"],choices=r["choices"])
        if f:=r.get("policy_failure"):
            item["parent"]=f["parent"]
            item["actual"]=json.loads((views/(f["actual"]+".json")).read_bytes())
            item["predicted"]={v:json.loads((views/(v+".json")).read_bytes()) for v in f["expected"]}
            item["nearest"]=min((diff(v,item["actual"]) for v in item["predicted"].values()),key=len)
        else:
            item["last_public"]=r["boundaries"][-1]
        findings.append(item)
    pack(out/"findings.jsonl.gz",findings)

if __name__=="__main__":audit(*sys.argv[1:])
