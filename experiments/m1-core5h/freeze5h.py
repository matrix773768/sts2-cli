import gzip,random,sys
from paths5h import *
sys.path.insert(0,str(G))
from settings import A,load,digest,deck_for

def main():
    banned={f for s in load(A/"history.gz")["sources"].values() for f in s["families"]}
    for name,split in [("dev","dev"),("reserve","train"),("train","train")]:
        banned.update(r["family"] for r in load(A/(name+".gz"))[split])
    banned.update(r["family"] for r in read(G/"evidence/confirmation.json"))
    pool=ROOT/"logs/m1-dc1-formal/roots"
    donors={r["id"]:r for r in read(pool/"families.json")}
    role=next(r for r in read(pool/"catalog.json")["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    src=load(G.parent/"m1-core5d/evidence/panel.gz")["train"]
    for group,n,worlds in [("confirm",128,2),("open",960,1)]:
        rows=[]
        ordered=sorted(src,key=lambda r:digest(["5h-donor",group,r["family"]]))
        for i in range(n):
            d=donors[ordered[i%len(ordered)]["family"]]
            rng=random.Random(digest(["5h",group,i]))
            while True:
                ids,rate=deck_for(role,cards,d["spec"]["act"],d["source"],d["package"],rng)
                f=digest(sorted(ids))
                if ids and f not in banned:break
            banned.add(f)
            rng.shuffle(ids)
            deck=[dict(id=c,upgrade=int(cards[c]["upgradable"] and rng.random()<rate)) for c in ids]
            for j in range(worlds):
                s=d["spec"]|dict(deck=deck,seed=digest(["5h-world",f,j])[:16].upper())
                rows.append(dict(family=f,spec=s))
        with gzip.open(E/(group+".gz"),"wt",encoding="utf8") as out:json.dump(rows,out,separators=(",",":"))
if __name__=="__main__":main()
