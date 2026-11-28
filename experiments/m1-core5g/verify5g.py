"""Verify the finished artifact graph, independently of training and model selection."""
import ast,gzip,hashlib,json
from pathlib import Path
from collections import Counter
from settings import *

def main():
    rel=read(A/"release.json")
    assert rel["id"]==RELEASE
    split=read(A/"splits.json")
    assert sha(A/"splits.json")==rel["artifacts"]["splits.json"]
    source=load(A/"history.gz")
    banned={f for s in source["sources"].values() for f in s["families"]}
    for ed,part in [("train","train"),("dev","dev"),("reserve","train")]:
        banned.update(x["family"] for x in load(A/(ed+".gz"))[part])
    panel=read(OUT/"confirmation.json")
    fs=Counter(digest(sorted(c["id"] for c in x["spec"]["deck"])) for x in panel)
    assert len(fs)==160 and set(fs.values())=={2} and not set(fs)&banned
    assert set(x["family"] for x in panel)==fs.keys() and len({x["spec"]["seed"] for x in panel})==320
    assert not set(split["primary_train"])&set(split["new_dev_attempts"]+source["core5f"]["dev"]+split["extended_train"])
    assert sum(p.numel() for p in Value().parameters())==31596
    checks=0
    for p in OUT.glob("*.pt"):
        r=read(p.with_suffix(".json"))
        assert sha(p)==r["sha256"]
        Value().load_state_dict(torch.load(p,weights_only=True))
        checks+=1
    assert checks==34
    selection=read(OUT/"selection.json")
    receipt_count=0
    for stage,arms,specs in [("dev",selection["entries"],read(OUT/"dev-battles.json")),("confirm",selection["confirm"],panel)]:
        for arm in arms:
            rows=[]
            for chunk in range((len(specs)+63)//64):
                name=f"{stage}-{arm}-{chunk}"
                result=read(OUT/(name+".json"))
                assert result["raw"]==sha(WORK/name/"natural.jsonl.gz")
                ident=result["ledger"]["policy"]
                assert ident["id"]==digest({k:v for k,v in ident.items() if k!="id"})
                if arm=="v2":assert ident["id"]==POLICY
                else:assert (ident["parent"],ident["value"],ident["loader"])==(POLICY,sha(OUT/(arm+".pt")),sha(G/"battle.py"))
                rows.extend(result["rows"])
                receipt_count+=1
            assert [(r["family"],r["seed"]) for r in rows]==[(r["family"],r["spec"]["seed"]) for r in specs]
            assert all((r["end"] is None)==(r["status"]=="failed") for r in rows)
    for p in G.glob("*.py"):ast.parse(p.read_text(encoding="utf8"))
    print("Verified",checks,"checkpoints,",receipt_count,"battle receipts and all panel identities.")
if __name__=="__main__":main()
