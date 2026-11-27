"""Composition-exclusive sealed evaluation and preassigned open sampling roots."""
import gzip,json,os,random,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core5d"))
from panel5d import ROOT,FIVE,cohort,deck_for,digest,read,load,rows
D=HERE.parent/"m1-core5d/evidence"
RUN=Path(os.environ.get("STS2_CORE5E_RUN",HERE)).resolve()
E=RUN/"evidence"
OUT=ROOT/"logs/core5e" if RUN==HERE else RUN/"logs"
WORLD=Path(os.environ.get("STS2_CORE5E_WORLD",ROOT/"logs/core5e-world-host"))
def freeze():
    old=load(FIVE/"evidence/panels.gz")
    d=load(D/"panel.gz");extra=load(D/"augmentation.gz")
    families=read(ROOT/"logs/m1-dc1-formal/roots/families.json")
    meta={r["id"]:r for r in families}
    seen={r["deck_family"] for r in families}
    seen.update(digest(sorted(c["id"] for c in s["deck"])) for s in (
        [j[1] for j in old["confirm"]]+[w["spec"] for panel in (
        load(HERE.parent/"m1-core5b/evidence/panel.gz")["fresh"],
        load(HERE.parent/"m1-core5c/evidence/protocol.gz")["fresh"],d["confirm"]) for w in panel]))
    role=next(r for r in read(ROOT/"logs/m1-dc1-formal/roots/catalog.json")["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    confirm=[]
    for w in sorted(d["train"],key=lambda w:digest(["5e-donor",w["family"]]))[:64]:
        donor=meta[w["family"]];spec=donor["spec"]
        rng=random.Random(digest(["5e-deck",w["family"]]))
        while True:
            ids,rate=deck_for(role,cards,spec["act"],donor["source"],donor["package"],rng)
            if ids and digest(sorted(ids)) not in seen:break
        seen.add(digest(sorted(ids)));rng.shuffle(ids)
        spec=spec|dict(deck=[dict(id=c,upgrade=int(cards[c]["upgradable"] and rng.random()<rate)) for c in ids])
        family=digest(spec)
        confirm.extend(dict(spec=spec|dict(seed=cohort.seed(family,"5e-confirm",i)),family=family) for i in range(2))
    selection=[w|dict(spec=w["spec"]|dict(seed=cohort.seed(w["family"],"5e-selection",i)))
               for w in d["selection"][:12] for i in range(3)]
    def sources(name,data):
        return [w|dict(source=name,index=i) for i,w in enumerate(data)]
    train=sorted(sources("train",d["train"]),key=lambda w:digest(["5e-roots",w["family"]]))[:128]
    dev=sources("dev",d["dev"])+sources("dev2",extra["dev2"][:24])
    E.mkdir(parents=True,exist_ok=True)
    with gzip.open(E/"panel.gz","xt") as f:json.dump(dict(confirm=confirm,selection=selection,train=train,dev=dev),f)
if __name__=="__main__":freeze()
