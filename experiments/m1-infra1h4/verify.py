"""Offline checks on H4 evidence. No model, native executable or local worker logs required."""
from collections import Counter,deque
import gzip
import hashlib
import json
from math import isclose
from pathlib import Path

E=Path(__file__).resolve().parent/"evidence"

def rows(name):
    with gzip.open(E/(name+".jsonl.gz")) as f:return list(map(json.loads,f))

def boundary(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def walk(row):
    actual={c["turn"]-1:boundary([c,list(c["belief"]["counts"])]) for c in row["states"]}
    if row["terminal"]:
        t=row["terminal"]
        actual[t["turn"]]=boundary([row["status"],t["hp"],t["max_hp"],t["gold"]])
    pending=deque(row.get("executed_bindings",[]))
    for q in row["queries"]:
        for option in [q["reference_law"],*q["options"]]:
            assert isclose(option["coverage"]+sum(option["gaps"].values()),1,abs_tol=1.e-8)
        if "policy" not in q:continue
        assert all(p>0 for p in q["law"].values())
        assert isclose(sum(q["law"].values()),1,abs_tol=1.e-8)
        if row["terminal"]:
            assert q["matched"] and q["observed"] in q["law"]
            assert actual[q["turn"]]==q["observed"]
        edges=q["policy"];menu={(e["parent"],e["view"]):e for e in edges}
        assert len(menu)==len(edges)
        children={e["parent"] for e in edges}
        node=0
        # Some stochastic children terminate directly; the next turn starts at parent zero.
        while node in children:
            if not pending:break
            parent,view,index=pending[0]
            if node!=parent:break
            edge=menu[(parent,view)]
            assert edge["index"]==index
            if not node:assert index==q["selected"]
            node=edge["node"]
            pending.popleft()
    assert not pending

def verify():
    manifest=json.loads((E/"sha256.json").read_bytes())
    assert set(manifest)=={p.name for p in E.iterdir() if p.is_file() and p.name!="sha256.json"}
    for name,h in manifest.items():assert hashlib.sha256((E/name).read_bytes()).hexdigest()==h,name
    book=json.loads((E/"ledger.json").read_bytes())
    assert 0<book["worker_seconds"]<=120*60
    for arm,stats in book["arms"].items():
        rs=rows(arm)
        assert len(rs)==len({r["i"] for r in rs})==(32 if arm.startswith("open-") or arm=="post-open-fixed" else 96)
        assert Counter(r["status"] for r in rs)==stats["status"]
        assert not stats["cost"]["diagnostic"]
        assert {r["split"] for r in rs}==({"custom"} if arm.startswith("open-") or arm=="post-open-fixed" else {"train"})
        assert stats["C_completed"]==sum(len(r["states"]) for r in rs if r["terminal"])
        for r in rs:walk(r)
    states={}
    for s in rows("selected-states"):
        state=s["state"];kind=s["kind"]
        key=boundary([state,list(state["belief"]["counts"])]) if kind=="C" else boundary([kind,state["hp"],state["max_hp"],state["gold"]])
        assert key==s["key"]
        states[key]=s
    targets={(r["i"],q["turn"]):q for r in rows("post-fix96") for q in r["queries"] if "policy" in q}
    for record in rows("selected-laws"):
        q=targets.pop((record["i"],record["turn"]))
        nodes={e["node"] for e in q["policy"]};mass=Counter();total=0.
        for leaf in record["leaves"]:
            assert leaf["cursor"] in nodes and leaf["key"] in states
            mass[leaf["key"]]+=leaf["mass"];total+=leaf["value"]*leaf["mass"]
        assert dict(mass)==q["law"] and total==record["evaluated_value"]
    assert not targets
    candidate=rows("candidate32")
    full={r["i"] for r in rows("candidate32-full-native") if r["status"]=="matched"}
    assert rows("candidate32-reviewed")==[r for r in candidate if r["i"] in full]
    assert len(full)==93 and sum(len(r["states"]) for r in candidate if r["i"] in full)==496
    for label,source in (("release96-native","post-fix96"),("release-open-native","post-open-fixed")):
        run=rows(source);native=rows(label)
        assert [r["i"] for r in run]==[r["i"] for r in native]
        accepted=[r for r,v in zip(run,native) if v["status"]=="matched"]
        assert accepted==rows(source+"-reviewed")
        assert sum(len(r["states"]) for r in accepted)==book["native_followups"][label]["C"]
    assert {r["i"] for r in rows("gardens-native") if r["status"]=="matched"}=={23,86,89}
    check=rows("historical-failure-replay")
    assert len(check)==12 and sum(r.get("matched") is True for r in check)==9
    assert all(r["status"]=="active" and "policy_divergence" not in r for r in check)
    assert len(rows("native-draw-cuts"))==33 and all(r["status"]=="observed" for r in rows("native-draw-cuts"))
    root,=rows("candidate123")
    assert root["invariant"] and root["status"]=="matched" and len(root["worlds"])==12
    assert book["worlds"]["candidate123"]["native"]=={"matched":6}
    opens=rows("open-hot")
    assert len({r["family"] for r in opens})==32
    assert not {r["family"] for r in opens}.intersection(r["family"] for r in candidate)
    assert not {r["seed"] for r in opens}.intersection(r["seed"] for r in candidate)
    final=book["native_followups"]["release96-native"]
    print(f"Verified {len(manifest)} evidence files, {len(book['arms'])} attempt denominators, {final['reviewed']} final native-reviewed battles and {final['C']} C.")

if __name__=="__main__":verify()
