import sys,json,gzip,random
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core5a"))
from freeze import FIVE,panels,ROOT,read,digest,deck_for
from core4_roots import cohort
from paths5b import E,LOGS
def records(path):
    with gzip.open(path,"rt",encoding="utf8") as f:yield from map(json.loads,f)
def freeze():
    old=json.load(gzip.open(FIVE/"evidence/panels.gz","rt"))
    dead=[]
    for arm in ("original","v1","v2"):
        dead.append({(r["family"],r["seed"]) for f in (FIVE/"evidence").glob(f"confirm-{arm}-*.gz") for r in records(f) if r["status"]=="death"})
    historical=[dict(family=j[3],spec=j[1]|dict(seed=cohort.seed(j[3],"core5a-confirm",rep))) for rep in range(3) for j in old["confirm"]]
    losses=set.intersection(*dead)
    ordered=sorted(historical,key=lambda w:digest(["5b",w]))
    def select(hard,n,exclude):
        ans=[]
        for w in ordered:
            fam=w["family"];s=w["spec"]
            if fam in exclude or s["max_hp"]!=80 or ((fam,s["seed"]) in losses)!=hard:continue
            exclude.add(fam);ans.append(w|dict(hard=hard))
            if len(ans)==n:break
        return ans
    hard=select(True,40,set());exclude={w["family"] for w in hard[:24]}
    high=hard[:24]+select(False,24,exclude)
    families=read(ROOT/"logs/m1-dc1-formal/roots/families.json")
    ban={r["deck_family"] for r in families}|{digest(sorted(c["id"] for c in j[1]["deck"])) for j in old["confirm"]}
    meta={r["id"]:r for r in families}
    cat=read(ROOT/"logs/m1-dc1-formal/roots/catalog.json")
    role=next(r for r in cat["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    fresh=[]
    for j in sorted(old["train"],key=lambda j:digest(["5b-donor",j[3]])):
        s=meta[j[3]];spec=s["spec"]
        if spec["max_hp"]!=80:continue
        rng=random.Random(digest(["5b-deck",j[3]]))
        while True:
            names,rate=deck_for(role,cards,spec["act"],s["source"],s["package"],rng)
            if names and digest(sorted(names)) not in ban:break
        ban.add(digest(sorted(names)));rng.shuffle(names)
        spec=spec|dict(deck=[dict(id=x,upgrade=int(cards[x]["upgradable"] and rng.random()<rate)) for x in names])
        fam=digest(spec)
        for k in range(2):fresh.append(dict(family=fam,spec=spec|dict(seed=cohort.seed(fam,"5b",k))))
        if len(fresh)==96:break
    E.mkdir(parents=True,exist_ok=True)
    LOGS.mkdir(parents=True,exist_ok=True)
    with gzip.open(E/"panel.gz","xt") as f:json.dump(dict(historical=historical,oracle=hard,high=high,fresh=fresh),f)
if __name__=="__main__":freeze()
