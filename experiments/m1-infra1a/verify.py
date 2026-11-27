"""Verify committed receipts and every complete record against the independent 0B campaign."""
import gzip
from hashlib import sha256
import zipfile
from common import E, OLD, json
from semantic_check import digest

def verify():
    book=json.loads((E/"campaign.json").read_bytes())
    baseline=json.loads((OLD/"evidence/formal/campaign.json").read_bytes())
    expected={}
    with zipfile.ZipFile(OLD/"evidence/formal/production-receipts.zip") as frozen:
        for row in baseline:
            kind=row.get("kind")
            if (kind in expected or row.get("mode")!="baseline" or row.get("arm")!="V2"
                    or row.get("n")!=1 or row.get("smoke")):
                continue
            d=row["tag"]+"/worker-0/"
            meta=json.loads(frozen.read(d+"worker.json"))
            raw=frozen.read(d+"evidence/"+meta["closed"]["file"])
            ordered={}
            for record in map(json.loads,gzip.decompress(raw).splitlines()):
                record.pop("seconds",None)
                ordered[str(record["i"])]=digest(record)
            assert ordered==row["semantics"]
            expected[kind]=ordered
    checks=[]
    shadows={}
    hits=[]
    active_evidence={}
    with zipfile.ZipFile(E/"production.zip") as z:
        if z.testzip():raise ValueError("Receipt archive CRC failed")
        for row in book:
            if not row.get("success") or "kind" not in row:continue
            tag=row["label"];d=tag+"/worker-0/"
            result=json.loads(z.read(tag+"/result.json"))
            meta=json.loads(z.read(d+"worker.json"))
            raw=z.read(d+"evidence/"+meta["closed"]["file"])
            assert sha256(raw).hexdigest()==result["workers"][0]["file_sha256"]
            records=list(map(json.loads,gzip.decompress(raw).splitlines()))
            ids=[]
            for r in records:
                r.pop("seconds",None)
                i=str(r["i"]);ids.append(i)
                if digest(r)!=expected[row["kind"]][i]:
                    raise ValueError(f"{tag}/{i} differs from frozen 0B production")
            assert len(ids)==len(set(ids))==row["matched"]
            if not row["smoke"]:assert ids==list(expected[row["kind"]])
            checks.append(dict(tag=tag,checked=len(ids),totals=row["totals"]))
            if row["variant"]=="shadow":
                detail=json.loads(gzip.decompress(z.read(d+"shadow.json.gz")))
                shadows[row["kind"]]=detail["rows"]
            if row["variant"]=="reuse":
                active=json.loads(z.read(d+"reuse.json"))
                active_evidence[row["label"]]=dict(kind=row["kind"], wall=row["wall"],
                    stats=active["stats"], matched_shadow_seconds=0.0)
                hits.extend((tag,row["kind"],r) for r in active["hits"])
        for tag,kind,r in hits:
            group=[x for x in shadows[kind] if x["key"]==r["key"] and "output" in x]
            assert len(group)>1 and all(x["output"]==group[0]["output"] for x in group)
            matched=[x for x in group if x["location"]==r["location"] and x["turn"]==r["turn"]
                     and x["query"]["calls"]==r["calls"]]
            assert len(matched)==1
            active_evidence[tag]["matched_shadow_seconds"]+=matched[0]["elapsed_ns"]/1e9
    out=dict(checks=checks,active_evidence=active_evidence,checked_active_hits=len(hits),charged_s=sum(r["seconds"] for r in book),
             failed=[r["label"] for r in book if not r["success"]])
    (E/"verification.json").write_text(json.dumps(out,indent=2))
    print(len(checks),"treatments,",sum(r["checked"] for r in checks),"records,",len(hits),"verified active hits")
if __name__=="__main__":verify()
