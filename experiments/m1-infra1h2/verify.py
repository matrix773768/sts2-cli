"""Check the A-D evidence without launching a game or model."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
E=HERE/"evidence"
def read(name):return json.loads((E/name).read_bytes())
def verify():
    private=read("private.json")
    assert sum(e["stage"]=="terminal" for e in private)==91
    stops={e["root"]:e for e in private if e["stage"]=="stop"}
    assert set(stops)=={7,13,35,74,92}
    native={(x["ordinal"],x["step"]):x for x in read("native.json")}
    for i,e in stops.items():
        actual=native[i,e["steps"]]
        assert actual["reached"]==e["steps"] and "error" not in actual
        value=int(e["detail"].split("/")[1 if e["detail"].startswith("max_hp") else 2])
        if e["detail"].startswith("max_hp"):assert value==actual["stamp"]["player_max_hp"]
        else:assert actual["native"]["decision"]=="card_reward" and value==actual["stamp"]["player_hp"]
    b=read("branches.json")
    assert len(b["roots"])==6
    assert all(x.get("equal",True) for x in b["edges"])
    assert all(x.get("tensor_equal",True) and x.get("value_equal",True) for x in b["edges"])
    assert all(not c["delta"] for x in b["edges"] for c in x.get("children",[]))
    for x in b["edges"]:
        if "follow_kind" in x:assert x["follow_equal"] and x["follow_delta"]==[]
    turns=read("turns.json")
    real=next(r for r in turns if r["panel"]=="0")
    assert real["planner_delta"]==real["graph_delta"]==[] and real["C_tensors_equal"]
    assert real["candidate"]==real["reference"] and real["candidate"]["calls"]==1305
    assert real["nodes"]==41 and real["conditional_replies"]==280
    assert read("invariance.json")["equal"]
    slug=read("slug123.json")
    assert len(slug["edges"])==35 and all(e.get("equal") for e in slug["edges"])
    assert all(p["law_equal"] and p["public_C_equal"] and p["tensor_equal"] and p["same_batch_v2_equal"]
               for p in slug["programs"])
    for name in ("natural-cost","natural-final","natural-census","audit-ba","audit-ha"):
        assert read(name+".json")["archive_differences"]==[],name
    full=read("natural-census.json")
    assert len(full["ids"])==full["terminal"]==96 and full["queries"]==len(full["hot_turns"])==607
    assert sum(r["committed"] for r in full["hot_turns"])==1
    pair=[read(n+".json") for n in ("natural-cost","natural-final")]
    assert pair[0]["hashes"]==pair[1]["hashes"] and len(pair[0]["baseline_cost"])==55
    for r in pair:assert r["terminal"]==8
    assert read("ledger.json")["worker_seconds"]<=7200
    print("Verified private, public, Planner, information-set, production, and budget receipts.")
if __name__=="__main__":verify()
