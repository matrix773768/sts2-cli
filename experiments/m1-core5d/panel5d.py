"""Freeze fresh deck compositions and all experiment splits before sampling trajectories."""
import gzip,json,os,random,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core5c"))
from panel5c import ROOT,FIVE,cohort,digest,read,deck_for
RUN=Path(os.environ.get("STS2_CORE5D_RUN",HERE)).resolve()
E=RUN/"evidence"
OUT=(ROOT/"logs/core5d") if RUN==HERE else RUN/"logs"
def load(path):
    with gzip.open(path,"rt",encoding="utf8") as f:return json.load(f)
def rows(path):
    with gzip.open(path,"rt",encoding="utf8") as f:yield from map(json.loads,f)
def freeze():
    old=load(FIVE/"evidence/panels.gz")
    fresh5b=load(HERE.parent/"m1-core5b/evidence/panel.gz")["fresh"]
    fresh5c=load(HERE.parent/"m1-core5c/evidence/protocol.gz")["fresh"]
    families=read(ROOT/"logs/m1-dc1-formal/roots/families.json")
    meta={r["id"]:r for r in families}
    banned={r["deck_family"] for r in families}
    for s in [j[1] for j in old["confirm"]]+[w["spec"] for w in fresh5b+fresh5c]:
        banned.add(digest(sorted(c["id"] for c in s["deck"])))
    catalog=read(ROOT/"logs/m1-dc1-formal/roots/catalog.json")
    role=next(r for r in catalog["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    def donors(split,tag):
        return sorted((j for j in old[split] if j[1]["max_hp"]==80),key=lambda j:digest([tag,j[3]]))
    panel={}
    for group,split,count in (("train","train",256),("dev","dev",24),("selection","dev",12)):
        jobs=donors(split,"5d-"+split)
        if group=="selection":jobs=jobs[24:]
        panel[group]=[dict(family=j[3],spec=j[1]|dict(seed=cohort.seed(j[3],"5d-"+group,0))) for j in jobs[:count]]
    fresh=[]
    for j in donors("train","5d-confirm")[:48]:
        donor=meta[j[3]]
        s=donor["spec"];rng=random.Random(digest(["5d-composition",j[3]]))
        while True:
            names,rate=deck_for(role,cards,s["act"],donor["source"],donor["package"],rng)
            if names and digest(sorted(names)) not in banned:break
        banned.add(digest(sorted(names)));rng.shuffle(names)
        spec=s|dict(deck=[dict(id=k,upgrade=int(cards[k]["upgradable"] and rng.random()<rate)) for k in names])
        family=digest(spec)
        fresh.extend(dict(family=family,spec=spec|dict(seed=cohort.seed(family,"5d-confirm",rep))) for rep in range(2))
    panel["confirm"]=fresh
    panel["selection"] += [w|dict(spec=w["spec"]|dict(seed=cohort.seed(w["family"],"5d-selection",1))) for w in panel["selection"]]
    E.mkdir(parents=True,exist_ok=True)
    with gzip.open(E/"panel.gz","xt") as f:json.dump(panel,f)
if __name__=="__main__":freeze()
