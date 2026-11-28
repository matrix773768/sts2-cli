"""Verify the frozen manifests, raw readback and historical positive/negative controls."""
import json,gzip,time
from collections import Counter
from branch import H,E,W,Actor
from common6 import read,save,sha,INFRA
from client import BUILD
from engine.HotSearch.experience import read_rows

def load(name):
    return json.load(gzip.open(E/name))

def audit():
    start=time.perf_counter()
    selection=read(E/"selection.json");panel=load("confirm.gz");results=read(E/"results.json")
    bin_dir=BUILD/"bin/Release/net9.0"
    binaries={"host":sha(bin_dir/"OfflineSearchHarness.dll"),"hot":sha(bin_dir/"CombatSolver.dll"),
              "game":sha(INFRA/"lib/sts2.dll")}
    assert binaries==read(BUILD/"identity.json")
    assert selection["panel_sha"]==sha(E/"confirm.gz") and selection["protocol_sha"]==sha(H/"protocol.md")
    families=Counter(r["family"] for r in panel)
    assert len(families)==192 and set(families.values())=={2} and len({r["spec"]["seed"] for r in panel})==384
    old=H.parent/"m1-core6b1/evidence"
    reg=load("regression.gz")["roots"]
    assert set(reg)=={r["id"] for r in read(old/"panel.json")["roots"]}
    for key,r in reg.items():
        historical=json.load(gzip.open(old/(key+".gz")))
        for arm,name in (("v2","h5"),("low","low")):
            current=r["arms"][arm];entry=current["options"][current["best"]]["q"]
            orig=historical["graphs"][historical["selected"][name]]["q"]
            assert (entry["index"],entry["coverage"])==(orig["index"],orig["coverage"])
            if orig["value"] is None:assert entry["value"] is None
            else:assert abs(entry["value"]-orig["value"])<.002
        if r["arms"]["low"]["options"][0]["q"]["value"] is None:
            for a in ("target","general","expand"):
                assert len(r["arms"][a]["options"])==1
    baseline_checks={}
    for a in ("v2","low"):
        here=read(E/f"dev-{a}-0.json")["rows"]
        before=read(H.parent/f"m1-core6a/evidence/dev-{a}-0.json")["rows"][:len(here)]
        for x,y in zip(here,before,strict=True):
            assert all(x[k]==y[k] for k in ("family","seed","status","end","queries","closed","steps"))
        baseline_checks[a]=len(here)
    inventory={}; verified=Counter()
    for stage,arms in (("dev",["v2","low","expand","target","general"]),("confirm",selection["arms"])):
        for arm in arms:
            for f in sorted(E.glob(f"{stage}-{arm}-*.json")):
                re=read(f);root=W/f.stem
                assert re["policy"]["id"]==Actor(arm).identity("tactical",32)["id"]
                for field,file in (("public",root/"public.gz"),("raw",root/"engine/natural.jsonl.gz")):
                    assert sha(file)==re[field]
                for row,raw in zip(re["rows"],read_rows(root/"engine/natural.jsonl.gz"),strict=True):
                    assert (row["end"] is None)==(row["status"]=="failed")
                    assert row["reason"] if row["status"]=="failed" else row["reason"] is None
                    if row["status"]=="failed":assert raw["terminal"] is None
                    assert row["realized"]<=sum(row["branch_winners"].values())
                    for q in raw["queries"]:
                        if q["reference_law"]["value"] is None:
                            assert "winner_style" not in q and not q["committed"]
                            if arm!="v2":assert not q["options"]
                        for opt in q["options"]:
                            assert (opt["value"] is None)==bool(opt["gaps"])
                            assert abs(opt["coverage"]+sum(opt["gaps"].values())-1)<1e-7
                    verified[stage]+=1
                inventory[f.name]=sha(f)
    assert verified["confirm"]==len(panel)*len(selection["arms"])
    assert not results["gate"]["passed"] or results["gate"]["utility_lower"]>0
    save(E/"audit.json",dict(baseline_development_replays=baseline_checks,verified=verified,binaries=binaries,receipt_sha256=inventory,
        seconds=time.perf_counter()-start))
if __name__=="__main__":audit()
