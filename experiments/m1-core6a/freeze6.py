"""Freeze the new confirmation at family level before fitting or simulating."""
import gzip
import random
import sys
from pathlib import Path
H=Path(__file__).resolve().parent
sys.path.insert(0,str(H.parent/"m1-core5g"))
from settings import A,ROOT,load,read,digest,deck_for

def main():
    banned={f for source in load(A/"history.gz")["sources"].values() for f in source["families"]}
    for edition,key in [("train","train"),("dev","dev"),("reserve","train")]:
        banned.update(r["family"] for r in load(A/(edition+".gz"))[key])
    banned.update(r["family"] for r in read(H.parent/"m1-core5g/evidence/confirmation.json"))
    for name in ("open","confirm"):
        banned.update(r["family"] for r in load(H.parent/f"m1-core5h/evidence/{name}.gz"))
    assets=ROOT/"logs/m1-dc1-formal/roots"
    donors={r["id"]:r for r in read(assets/"families.json")}
    role=next(c for c in read(assets/"catalog.json")["characters"] if c["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    src=sorted(load(H.parent/"m1-core5d/evidence/panel.gz")["train"], key=lambda r:digest(["6a-donor",r["family"]]))
    rows=[]
    for i in range(320):
        d=donors[src[i%len(src)]["family"]]
        rng=random.Random(digest(["6a-deck",i]))
        while True:
            ids,rate=deck_for(role,cards,d["spec"]["act"],d["source"],d["package"],rng)
            family=digest(sorted(ids))
            if ids and family not in banned:break
        banned.add(family)
        rng.shuffle(ids)
        deck=[dict(id=c,upgrade=int(cards[c]["upgradable"] and rng.random()<rate)) for c in ids]
        for j in range(2):
            rows.append(dict(family=family,spec=d["spec"]|dict(deck=deck,seed=digest(["6a-seed",family,j])[:16].upper())))
    import json
    (H/"evidence").mkdir(exist_ok=True)
    with gzip.open(H/"evidence/confirm.gz","xt",encoding="utf8") as out:json.dump(rows,out,separators=(",",":"))
if __name__=="__main__":main()
