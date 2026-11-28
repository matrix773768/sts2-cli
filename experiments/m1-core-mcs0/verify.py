"""Offline integrity, historical parity, probability and finite-graph certificate checks."""
import argparse, hashlib
from collections import Counter
from pathlib import Path
from freeze import H,E,read,gz,sources,save,digest
from certificate import certificate

def sha(p):
    data=p.read_bytes()
    if p.suffix in (".py",".md",".json"):
        data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()

def main(seal):
    rows=read(E/"results.json")["rows"]
    meta=read(E/"panel.json")
    roots=sources()
    historical=gz(H.parent/"m1-core6b2/evidence/regression.gz")["roots"]
    config=read(H/"panel.json")
    assert config["ids"]==[r["id"] for r in meta]
    assert set(rows)==set(roots)==set(config["ids"]) and len(rows)==64
    assert len(historical)==40 and set(historical)<=rows.keys()
    assert len({r["family"] for r in meta if r["group"]=="dev"})==24
    compression=read(E/"compression.json")["roots"]
    review=read(E/"review.json")["roots"]
    gap_differences=[]
    for info in meta:
        id_=info["id"]
        source=roots[id_]
        assert info["prefix_sha256"]==digest(source["steps"])
        assert info["view"]==source["root"]["view"] and source["spec"]["seed"]==info["seed"]
        raw=gz(E/"panel"/(id_+".gz"))
        c=certificate(raw)
        if id_ in historical:
            for mode,a in raw["arms"].items():
                old=historical[id_]["arms"][mode]
                assert old["best"]==a["best"]
                for j,(new,former) in enumerate(zip(a["options"],old["options"],strict=True)):
                    q,prior=new["q"],former["q"]
                    assert (q["value"],q["index"],q["style"])==(prior["value"],prior["index"],prior["style"])
                    if q["gaps"]!=prior["gaps"]:
                        assert q["value"] is None and abs(sum(q["gaps"].values())-sum(prior["gaps"].values()))<1e-8
                        gap_differences.append([id_,mode,j])
        if c["feasible"] is not None:
            assert abs(c["feasible"]-review[id_]["q"]["value"])<1e-4
        if rows[id_]["exact"] is not None:
            assert review[id_]["recheck"]["native_menus"]==len(raw["labels"])
            for i,k in enumerate(("legal","class_edges","response_classes")):
                expected=c[k] if i else raw["curve"][-1][k]
                assert compression[id_][str(i)]["classes"]==expected
        assert all(b["probes"]<=b["budget"] for b in raw["curve"])
    assert len(compression)==23 and len(review)==57
    assert gap_differences==[["enemy-07","general",0]]
    fx=read(E/"fixtures.json")
    assert fx["basic"]["finite"]["missing"]==fx["multi_target"]["finite"]["missing"]==0
    assert fx["upgrade"]["finite"]["missing"]==4
    trace=read(E/"b2-trace.json")["roots"]
    for witness in trace.values():
        assert any(a["card"]=="BODY_SLAM" and a["action"]["target"]==2 for a in witness["trace"])
        assert next(e["hp"] for e in witness["enemies"] if e["slot"]==2)==0
    assert read(E/"ledger.json")["charged_upper_seconds"]<=3600
    manifest=E/"manifest.json"
    hashes={str(p.relative_to(H).as_posix()):sha(p) for p in H.rglob("*") if p.is_file() and
            p!=manifest and "__pycache__" not in p.parts}
    if seal:save("manifest.json",hashes)
    assert hashes==read(manifest)
    print(f"Verified {len(rows)} public roots, {len(compression)} exact trees, {len(review)} feasible policies, {len(hashes)} files.")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--seal",action="store_true")
    main(p.parse_args().seal)
