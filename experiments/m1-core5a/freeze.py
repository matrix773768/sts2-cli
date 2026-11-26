"""Draw fresh deck compositions from the DC1 generator with legal open encounter donors."""
from search5 import FIVE
from core4_roots import panels,ROOT,read,digest
from dc_roots import deck_for
import gzip,json,random
from pathlib import Path

def freeze():
    old=panels()
    families=read(ROOT/"logs/m1-dc1-formal/roots/families.json")
    ban={r["deck_family"] for r in families}
    meta={r["id"]:r for r in families}
    catalog=read(ROOT/"logs/m1-dc1-formal/roots/catalog.json")
    role=next(r for r in catalog["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    donors=sorted(old["train"],key=lambda j:digest(["5a-donor",j[3]]))[:96]
    confirm=[]
    for j in donors:
        donor=meta[j[3]];s=donor["spec"];rng=random.Random(digest(["5a-build",j[3]]))
        while True:
            names,rate=deck_for(role,cards,s["act"],donor["source"],donor["package"],rng)
            if names and digest(sorted(names)) not in ban:break
        ban.add(digest(sorted(names)));rng.shuffle(names)
        spec=s|dict(deck=[dict(id=n,upgrade=int(cards[n]["upgradable"] and rng.random()<rate)) for n in names])
        confirm.append([len(confirm),spec,"confirm",digest(spec),j[4]])
    result=dict(train=old["train"],dev=old["dev"],confirm=confirm)
    with gzip.open(FIVE/"evidence/panels.gz","xt",encoding="utf8") as f:json.dump(result,f)
if __name__=="__main__":freeze()
