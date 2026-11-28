"""Strict, native-independent admission and read access to immutable HotSearch data shards."""
from collections import deque
import gzip
import hashlib
import json
from math import isclose,isfinite
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda:f.read(1024*1024),b""):h.update(part)
    return h.hexdigest()

def require(ok,msg):
    if not ok:raise ValueError(msg)

def probability(law):
    require(law and all(isfinite(p) and 0<p<=1+1e-8 for p in law.values()) and isclose(sum(law.values()),1,rel_tol=0,abs_tol=1e-8),"invalid closed law")

def check_queries(queries):
    for q in queries:
        for o in [q["reference_law"],*q["options"]]:
            pieces=[o["coverage"],*o["gaps"].values()]
            require(all(isfinite(m) and m>=0 for m in pieces) and abs(sum(pieces)-1)<1e-8,"unaccounted probability")
            require((o["value"] is None)==bool(o["gaps"]),"invalid option closure")
        if "policy" not in q:
            require(q["reference_law"]["value"] is None and not q["committed"] and q["reference"]==q["selected"],"unbound intervention")

def check_battle(r,initial=None):
    t=r["terminal"];status=r["status"]
    require(status in ("Victory","Defeat") and t is not None and (t["hp"]>0)==(status=="Victory"),"missing or inconsistent terminal")
    require(r["actual_steps"]==len(r["trace"])+len(r["choices"]) and len(r["trace"])==len(r.get("boundaries",[])),"action trace incomplete")
    require("policy_failure" not in r,"binding failure")
    check_queries(r["queries"])
    actual={c["turn"]-1:digest([c,list(c["belief"]["counts"])]) for c in r["states"]}
    actual[t["turn"]]=digest([status,t["hp"],t["max_hp"],t["gold"]])
    programs=[q for q in r["queries"] if "policy" in q]
    if initial:
        programs.insert(0,dict(r["intervention"],policy=initial["policy"],turn=r["trace"][0][0],selected=initial["first"]))
    pending=deque(r.get("executed_bindings",[]))
    for q in programs:
        probability(q["law"])
        require(q.get("matched") and q["observed"] in q["law"] and q["observed"]==actual[q["turn"]],"observed public boundary mismatch")
        edges={(e["parent"],e["view"]):e for e in q["policy"]}
        require(len(edges)==len(q["policy"]) and pending and pending[0][0]==0,"missing policy root")
        node=0
        while pending and pending[0][0]==node:
            parent,view,index=pending.popleft()
            edge=edges[parent,view]
            require(index==edge["index"] and (parent!=0 or index==q["selected"]),"unbound action")
            node=edge["node"]
    require(not pending,"unconsumed bindings")

def qualify(row,task):
    if task["kind"]=="natural":
        if row["status"]=="failed":
            require(row.get("terminal") is None and bool(row.get("reason")),"ambiguous failed battle")
            return False
        check_battle(row)
    else:
        if row["status"]!="matched":return False
        require(row["invariant"] and len(row["plans"])==2 and len(row["worlds"])==task["worlds"],"incomplete conditional cohort")
        check_queries(row["prefix"]["queries"])
        require(all(q.get("matched") is True for q in row["prefix"]["queries"] if "policy" in q),"failed prefix law")
        require(len({w["seed"] for w in row["worlds"]})==task["worlds"],"duplicate resampled world")
        for pair in [row["natural_pair"],*[w["outcomes"] for w in row["worlds"]]]:
            require(len(pair)==2,"missing intervention side")
            for plan,side in zip(row["plans"],pair):
                probability(plan["law"]);probability(plan["public_law"])
                require(side["matched"] and side["public_matched"] and side["observed"] in plan["law"] and side["public_key"] in plan["public_law"],"incomplete intervention")
                check_battle(side["trajectory"],plan)
    return True

def read_rows(path):
    with gzip.open(path,"rt",encoding="utf8") as stream:
        yield from map(json.loads,stream)

def scan(data,*,split,kind,policy_id=None,family=None,mechanism=None,native="not_run",eligible=True):
    """One frozen split and supervision type per call. Explicitly select a policy in a mixed-policy release."""
    data=Path(data);manifest=json.loads((data/"manifest.json").read_bytes())
    require(manifest["id"]==digest({k:v for k,v in manifest.items() if k!="id"}),"manifest integrity")
    ids={x["policy_id"] for x in manifest["shards"] if x["split"]==split and x["kind"]==kind}
    require(policy_id is not None or len(ids)<=1,"choose one behavior policy")
    for part in manifest["shards"]:
        if (part["split"],part["kind"])!=(split,kind) or (policy_id and policy_id!=part["policy_id"]):continue
        path=data/part["file"]
        require(sha(path)==part["sha256"],"shard digest mismatch")
        for r in read_rows(path):
            if r["eligible"]!=eligible or r["native_audit"]!=native:continue
            if family and r["family"]!=family:continue
            if mechanism and mechanism not in r["mechanisms"]:continue
            yield r
