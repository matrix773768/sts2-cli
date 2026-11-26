"""Public, ragged learning records. Distribution weights are local to a candidate."""
import gzip
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core1r2"))
from search import rule_context,mass_kind

from functools import lru_cache

@lru_cache(1)
def static_rules():
    with gzip.open(HERE/"catalog.json.gz","rt",encoding="utf8") as stream:return json.load(stream)

def encode(c):
    if c["setup"]["stage"]!="before_initial_draw": raise ValueError("Expected C")
    rules=rule_context(c)
    pressure=[]
    gaps=[]
    for e in c["enemies"]:
        graph=static_rules()["graphs"].get(e["species"]) or rules["graphs"].get(e["species"]) or []
        nodes={n["MoveId"]:n for n in graph}
        phase=e.get("phase") or {}
        node=nodes.get(phase.get("node"),{})
        following=nodes.get(node.get("next"),{})
        targets=following.get("targets") or ([node["next"]] if node.get("next") else [])
        pressure.append(dict(slot=e["slot"],rule=e["species"],node=node.get("MoveId"),
            next_node=node.get("next"),branch_condition=following.get("condition"),
            current_effects=node.get("effects",[]),possible_targets=targets,hits=e["attack_hits"],registers=phase.get("registers",{}),
            committed=phase.get("committed_moves",[])))
        if len(targets)>1 and not following.get("condition"):gaps.append(["enemy_condition",e["slot"]])
    if c["schema"]=="sts2.core.c.v2":gaps.append(["legacy_cost_layers"])
    if any(r.get("counter") is None for r in c["relics"]):gaps.append(["unexported_relic_counters"])
    for k in ("membership_gap","order_gap"):
        if c["belief"].get(k):gaps.append([k,c["belief"][k]])
    return dict(state=c,catalog="m1-core2/catalog.json.gz",pressure=pressure,missing=gaps,static_cards=sorted(rules["cards"]),
                static_graphs=sorted(rules["graphs"]))

def distribution(leaves):
    if any(not 0<=l["probability"]<=1 for l in leaves) or abs(sum(l["probability"] for l in leaves)-1)>1e-8:
        raise ValueError("invalid conditional mass")
    for l in leaves:
        kind=mass_kind(l)
        yield dict(source="counterfactual",qualification=kind,weight=l["probability"],
            strict_input=kind in ("C","death","victory"),witness=l["route"],setup=l.get("setup",[]),
            features=encode(l["state"]) if l["kind"]=="C" else None,
            outcome=l.get("state") if kind in ("victory","death") else None)

def batches(path,size=32):
    if size<1:raise ValueError("positive batch size required")
    with gzip.open(path,"rt",encoding="utf8") as stream:
        batch=[]
        for line in stream:
            batch.append(json.loads(line))
            if len(batch)==size:
                yield batch
                batch=[]
        if batch:yield batch
