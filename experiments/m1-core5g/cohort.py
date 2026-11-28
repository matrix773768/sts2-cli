import random
from settings import *

def main():
    h=load(A/"history.gz")
    banned={f for source in h["sources"].values() for f in source["families"]}
    for name,part in [("train","train"),("dev","dev"),("reserve","train")]:
        banned.update(r["family"] for r in load(A/(name+".gz"))[part])
    pool=ROOT/"logs/m1-dc1-formal/roots"
    donors={r["id"]:r for r in read(pool/"families.json")}
    role=next(r for r in read(pool/"catalog.json")["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    panel=[]
    for row in sorted(load(G.parent/"m1-core5d/evidence/panel.gz")["train"],key=lambda x:digest(["5g",x["family"]]))[:160]:
        d=donors[row["family"]]
        rng=random.Random(digest(["5g-panel",d["id"]]))
        s=d["spec"]
        while True:
            ids,rate=deck_for(role,cards,s["act"],d["source"],d["package"],rng)
            f=digest(sorted(ids))
            if ids and f not in banned:break
        banned.add(f)
        rng.shuffle(ids)
        deck=[dict(id=k,upgrade=int(cards[k]["upgradable"] and rng.random()<rate)) for k in ids]
        for i in range(2):panel.append(dict(family=f,spec=s|dict(deck=deck,seed=digest(["5g-world",f,i])[:16].upper())))
    save(OUT/"confirmation.json",panel)
    dev=set(h["core5f"]["dev"])|set(read(A/"splits.json")["new_dev_eligible"])
    sources=load(A/"dev.gz")["dev"]+load(H5/"cohort.json.gz")["train"]+load(H5/"capacity-cohort.json.gz")["train"]
    rows=sorted((r for r in sources if r["family"] in dev),key=lambda r:digest(["5g-development",r["family"]]))
    assert len(rows)==275
    save(OUT/"dev-battles.json",[dict(family=r["family"],spec=r["spec"]) for r in rows[:64]])
if __name__=="__main__":main()
