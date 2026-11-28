"""Attribute every frozen numeric mismatch using one-field replacement on the same C."""
import gzip
import json
from pathlib import Path
import sys
from diagnose import ROOT,HERE,diff
from models import strategic
from condition import key
from hot_produce import panel

def audit(source):
    old={r["i"]:r for p in (ROOT/"experiments/m1-core5d/evidence").glob("train-V2-*.gz") for r in map(json.loads,gzip.open(p))}
    ids=iter(panel());result=[];total=0
    folder,=(source/"transport").iterdir()
    replies=(json.loads(line) for line in (folder/"stdout.log").open("rb") if line.startswith(b'{"type":"hot"'))
    for cmd,reply in zip(map(json.loads,(folder/"commands.jsonl").open("rb")),replies):
        if cmd["op"]=="open":i=next(ids);index=0
        cut=(reply.get("result") or {}).get("observed_c")
        if not cut:continue
        actual=strategic(cut["facts"],cut["draw"]);expected=old[i]["states"][index];index+=1;total+=1
        if source.parent.name=="hotsearch":actual["setup"]["will_shuffle"]=actual["draw_count"]<actual["setup"]["draw"]
        if key(actual)==key(expected):continue
        paths=[k for k in expected if expected[k]!=actual.get(k)]
        if list(expected["belief"]["counts"])!=list(actual["belief"]["counts"]) and "belief" not in paths:paths.append("belief")
        sensitive=[k for k in paths if key(actual|{k:expected[k]})!=key(actual)]
        result.append(dict(i=i,turn=actual["turn"],fields=paths,affects_tensor=sensitive,detail=diff(actual,expected),
            old_counts=list(expected["belief"]["counts"]),hot_counts=list(actual["belief"]["counts"])))
    return dict(compared=total,mismatches=result)

if __name__=="__main__":
    d=audit(ROOT/sys.argv[1])
    with gzip.open(HERE/"evidence"/sys.argv[2],"wt",encoding="utf8") as f:json.dump(d,f,separators=(",",":"))
    from collections import Counter
    print(d["compared"],len(d["mismatches"]),Counter(tuple(v["affects_tensor"]) for v in d["mismatches"]))
