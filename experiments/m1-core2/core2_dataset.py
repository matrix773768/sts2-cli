"""Join public inputs and labels; no future trajectory or realized outcome in the encoder input."""
from state import *
from time import perf_counter
import zipfile
from collections import Counter

def enrich(c):
    data=encode(c)
    for e,pressure in zip(c["enemies"],data["pressure"]):
        windows=(e.get("phase") or {}).get("repeat_windows",{}).get(pressure["next_node"])
        if windows is not None:
            pressure["history_allowed"]=[w["target"] for w in windows if w["allowed_by_history"]]
        node=pressure["branch_condition"]
        if node:
            pressure["condition_inputs"]=dict(powers=e["powers"],registers=pressure["registers"])
    data["supply"]=[dict(power=p["id"],amount=p["amount"],rule_ref=p["id"] if p["id"] in static_rules()["powers"] else None)
                    for p in c["powers"]]
    if c["draw_count"]:
        data["missing"].append(["draw_instance_layers","public type bag and known positions only"])
    for power in data["supply"]:
        if power["rule_ref"] is None:data["missing"].append(["power_rule",power["power"]])
    return data

def learning_batches(path,size=32):
    if size<1:raise ValueError("positive batch size required")
    batch=[]
    trajectory={}
    for chunk in batches(path):
        for r in chunk:
            if r["source"]=="trajectory":trajectory={r["family"]:r["history"]}
            if r["source"]!="natural" or not r["terminal"]:continue
            sample=dict(input=enrich(r["features"]["state"]),past=trajectory[r["family"]][:r["position"]],
                family=r["family"],continuation=r["continuation"],source="natural",
                target=dict(terminal=r["terminal"],net_hp=r["net_hp"]))
            batch.append(sample)
            if len(batch)==size:
                yield batch
                batch=[]
    if batch:yield batch

def policy_batches(path,size=32):
    """Diagnostic candidate distributions. Each item has its own unit mass."""
    if size<1:raise ValueError("positive batch size required")
    batch=[]
    for group in batches(path):
        for row in group:
            if row["source"]!="public_policy":continue
            for leaf in row["distribution"]:
                if leaf["features"]:leaf["features"]=enrich(leaf["features"]["state"])
            batch.append(row)
            if len(batch)==size:
                yield batch
                batch=[]
    if batch:yield batch

def strict_batches(size=32):
    if size<1:raise ValueError("positive batch size required")
    source=HERE.parent/"m1-core1r2/evidence"
    with zipfile.ZipFile(source/"panel.zip") as panel:
        with gzip.open(source/"strict.json.gz","rt") as stream:rows=json.load(stream)["rows"]
        batch=[]
        prior=None
        for row in rows:
            f=row["family"]
            if f!=prior:
                detail=json.loads(gzip.decompress(panel.read(f+".json.gz")))
                queries={q["position"]:q for q in detail["queries"]}
                prior=f
            pos=row["position"]
            q=queries[pos]
            leaves=list(distribution(row["successors"]))
            for leaf in leaves:
                if leaf["features"]:leaf["features"]=enrich(leaf["features"]["state"])
            batch.append(dict(family=f,source="strict_rule_replay",past=detail["history"][:pos],
                root=q["graph"]["nodes"][0]["state"],policy=q["policy"],continuation=None,
                distribution=leaves,target=None))
            if len(batch)==size:
                yield batch
                batch=[]
        if batch:yield batch
