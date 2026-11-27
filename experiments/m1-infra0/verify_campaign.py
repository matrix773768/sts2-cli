"""Verify paired records, accounting, frozen parents and per-side instrumentation at closeout."""
import argparse
import hashlib
import zipfile
import gzip
import json
from campaign import RUNS,HERE,ROOT,ledger
from formal import semantic_rows
from semantic_check import digest
from world_assets import OPEN
from infra_assets import sha

def archived(paths):
    result={}
    for p in paths:
        for r in map(json.loads,gzip.open(p)):
            r.pop("seconds",None)
            result[r["i"]]=digest(r)
    return result

def verify_archive(out):
    book=json.loads((out/"campaign.json").read_bytes())
    groups={}
    with zipfile.ZipFile(out/"production-receipts.zip") as bundle:
        if bundle.testzip():raise ValueError("CRC mismatch")
        for entry in book:
            if not entry.get("success") or "tag" not in entry:continue
            tag=entry["tag"]
            result=json.loads(bundle.read(f"{tag}/result.json"))
            actual={}
            for j,receipt in enumerate(result["workers"]):
                prefix=f"{tag}/worker-{j}/"
                metadata=json.loads(bundle.read(prefix+"worker.json"))
                raw=bundle.read(prefix+"evidence/"+metadata["closed"]["file"])
                if hashlib.sha256(raw).hexdigest()!=receipt["file_sha256"]:
                    raise ValueError(f"{tag}: compressed shard changed")
                rows=[json.loads(line) for line in gzip.decompress(raw).splitlines()]
                if sorted(r["i"] for r in rows)!=sorted(receipt["ids"]):
                    raise ValueError(f"{tag}: shard membership changed")
                for row in rows:
                    row.pop("seconds",None)
                    actual[str(row["i"])]=digest(row)
            key=(entry["kind"],entry["arm"],entry["smoke"])
            if actual!=entry["semantics"] or actual!=groups.setdefault(key,actual):
                raise ValueError(f"{tag}: archived production changed")
    return sum("tag" in r and r["success"] for r in book)

def verify():
    out=HERE/"evidence/formal"
    book=ledger();groups={};checks=[]
    five=ROOT/"experiments/m1-core5d/evidence"
    historical={"initial-train":archived(OPEN.glob("worlds-train-*.gz")),
        "initial-dev":archived(OPEN.glob("worlds-dev-*.gz")),"audit":archived(OPEN.glob("audit12-train-*.gz")),
        "natural":archived(five.glob("train-V2-*.gz")),"pairs":archived(five.glob("pairs-train-*.gz"))}
    for r in book:
        if not r.get("success") or not r.get("tag"):continue
        folder=RUNS/r["tag"]
        result=json.loads((folder/"result.json").read_bytes());actual=semantic_rows(folder)
        key=r["kind"],r["arm"],r["smoke"]
        if actual!=groups.setdefault(key,actual):raise ValueError(f"Paired semantics failed: {r['tag']}")
        if {str(i):v for i,v in actual.items()}!=r["semantics"]:raise ValueError("Receipt changed")
        history=[] if r["arm"]!="V2" else [i for i,v in actual.items() if historical[r["kind"]][i]!=v]
        for job,receipt in zip(sorted(folder.glob("worker-*")),result["workers"]):
            w=json.loads((job/"worker.json").read_bytes());path=job/"evidence"/w["closed"]["file"]
            if sha(path)!=receipt["file_sha256"]:raise ValueError("Compressed output changed")
            if (job/"world-stages.json").exists():
                rows={z["i"]:z for z in map(json.loads,gzip.open(path))}
                roots=json.loads((job/"world-stages.json").read_bytes())
                assert len(roots)==len(rows) and sum(z["fixed_counts"].get("conditions/choose_root/n",0) for z in roots)==len(rows)
                for root in roots:
                    sides=root["sides"];case=rows[root["i"]]
                    assert len({(p["world"],p["side"]) for p in sides})==len(sides)
                    assert sum(len(z["outcomes"]) for z in case["worlds"])<=len(sides)<=2*len(case["worlds"])
                    assert sum(p["elapsed_ns"] for p in sides)+root["fixed_ns"]<=root["root_ns"]+1000
                    for side in sides:
                        if "suffix_inference" in side:
                            assert side["suffix_started"]
                            for network in ("G2","V2"):
                                for metric in ("n","ns"):
                                    key=f"{network}/forward/{metric}"
                                    assert 0<=side["suffix_inference"][key]<=side["delta"].get(key,0)
                assert w["stages"]["world_host/project/n"]>0
        checks.append(dict(tag=r["tag"],ids=len(actual),exact_within_campaign=True,archive_compared=r["arm"]=="V2",historical_differences=history))
    if verify_archive(out)!=len(checks):raise ValueError("Missing exported treatment")
    report=dict(checks=checks,worker_s=sum(r["worker_s"] for r in book),
        budget_s=7200,within_budget=sum(r["worker_s"] for r in book)<=7200)
    (out/"verification.json").write_text(json.dumps(report,indent=2))
    print(len(checks),"validated treatments")
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive-only",action="store_true")
    if parser.parse_args().archive_only:
        print(verify_archive(HERE/"evidence/formal"),"verified archived treatments")
    else:
        verify()
