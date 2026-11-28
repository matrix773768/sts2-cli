"""Deterministically preregister new compositions before any H5 outcomes are observed."""
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"experiments/m1-core5d"))
from panel5d import ROOT as PANEL_ROOT,deck_for,digest,load,read

def prepare(out):
    import os
    assets=Path(os.environ.get("HOTSEARCH_DC1_ROOT",ROOT/"logs/m1-dc1-formal/roots"))
    pool=read(assets/"families.json")
    meta={r["id"]:r for r in pool}
    role=next(r for r in read(assets/"catalog.json")["characters"] if r["name"]=="Ironclad")
    cards={r["id"]:r for r in role["cards"] if r["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    banned={digest(sorted(c["id"] for c in r["spec"]["deck"])) for r in pool}
    base=load(ROOT/"experiments/m1-core5d/evidence/panel.gz")
    # Use composition fingerprints for exclusion. No outcome or sealed trace is read.
    for group in base.values():
        banned.update(digest(sorted(c["id"] for c in r["spec"]["deck"])) for r in group)
    for path,group in [("m1-core5b/evidence/panel.gz","fresh"),("m1-core5c/evidence/protocol.gz","fresh")]:
        for r in load(ROOT/"experiments"/path)[group]:banned.add(digest(sorted(c["id"] for c in r["spec"]["deck"])))
    from panel5d import FIVE
    for group in load(FIVE/"evidence/panels.gz").values():
        for r in group:banned.add(digest(sorted(c["id"] for c in r[1]["deck"])))
    donors=sorted(base["train"],key=lambda r:digest(["H5-donor",r["family"]]))
    records={}
    for split,count in [("open",64),("train",512)]:
        data=[]
        for i in range(count):
            donor=meta[donors[i%len(donors)]["family"]]
            spec=donor["spec"]
            rng=random.Random(digest(["H5-1",split,i,donor["id"]]))
            for attempt in range(20000):
                names,rate=deck_for(role,cards,spec["act"],donor["source"],donor["package"],rng)
                family=digest(sorted(names)) if names else None
                if family and family not in banned:break
            else:raise RuntimeError("exhausted composition generator")
            banned.add(family);rng.shuffle(names)
            deck=[dict(id=k,upgrade=int(cards[k]["upgradable"] and rng.random()<rate)) for k in names]
            seed=digest(["H5-world",split,family])[:16].upper()
            data.append(dict(family=family,donor=donor["id"],spec=spec|dict(deck=deck,seed=seed)))
        records[split]=data
    historical=load(ROOT/"logs/infra0-world-inputs/panel.gz")["train"][123]
    records["bridge123"]=[historical]
    records["conditions"]=[r["family"] for r in sorted(records["train"],key=lambda r:digest(["H5-conditions",r["family"]]))[:64]]
    records["protocol"]=dict(version="m1-infra1h5-v1",natural="tactical",limit=32,margin=0,weights="frozen G2/V2",
        conditional_root_budget=128,conditional_turn=2,worlds=4,closed_reference=True,native_audit="not_run",
        open_analysis="64 fixed compositions, all attempts, terminal utility and HP loss, paired common-completion difference, high-budget corrected 1A",
        sampling="256 training donors in fixed hash order, two cycles for production; unique deck multisets across splits")
    out.parent.mkdir(exist_ok=True,parents=True)
    with out.open("xb") as file,gzip.GzipFile(fileobj=file,mode="wb",mtime=0,filename="") as z:
        z.write(json.dumps(records,ensure_ascii=False,separators=(",",":")).encode())
if __name__=="__main__":prepare(Path(sys.argv[1]))
