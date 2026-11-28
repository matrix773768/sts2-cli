"""Read-only validation of the committed evidence, without a simulator, logs or model runtime."""
import argparse,gzip,hashlib,json
from pathlib import Path
from collections import Counter
HOME_DIR=Path(__file__).resolve().parent
E=HOME_DIR/"evidence"
def read(path):
    with (gzip.open(path,"rb") if path.suffix==".gz" else path.open("rb")) as handle:return json.load(handle)
def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(seal=False):
    files={p.name:fingerprint(p) for p in sorted(E.iterdir()) if p.is_file() and p.name!="manifest.json"}
    pick=read(E/"selection.json");results=read(E/"results.json")
    assert fingerprint(HOME_DIR/"protocol.md")==pick["protocol_sha"]
    assert files["confirm.gz"]==pick["panel_sha"]
    panel=read(E/"confirm.gz")
    assert len(panel)==384 and set(Counter(x["family"] for x in panel).values())=={2}
    for arm in pick["arms"]:
        rows=[]
        for i in range(6):
            part=read(E/f"confirm-{arm}-{i}.json")
            assert part["policy"]["id"]==pick["policies"][arm]
            rows.extend(part["rows"])
        assert [(x["family"],x["seed"]) for x in rows]==[(x["family"],x["spec"]["seed"]) for x in panel]
        assert all((x["end"] is None)==(x["status"]=="failed") for x in rows)
        stats=results["stats"]["confirm"][arm]
        assert sum(x["end"] is not None for x in rows)==stats["complete"]
        assert sum(x["status"]=="Victory" for x in rows)==stats["wins"]
    assert read(E/"ledger.json")["total_upper"]<=7200
    manifest=E/"manifest.json"
    if seal:
        with manifest.open("x",encoding="utf8") as out:json.dump(files,out,indent=2)
    assert read(manifest)==files
    print(f"Verified {len(files)} files, {len(panel)} paired worlds and {len(pick['arms'])} frozen arms.")
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seal",action="store_true",help="Create manifest for a finished fresh run")
    verify(p.parse_args().seal)
