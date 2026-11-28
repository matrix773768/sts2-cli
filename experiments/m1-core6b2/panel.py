"""Freeze independent opening compositions using only historical opening manifests."""
import gzip,json,random,sys,time
from collections import Counter
from branch import H,E
from freeze6 import A,ROOT,load,read,digest,deck_for
from common6 import sha,save

def freeze(size):
    start=time.perf_counter()
    history=load(A/"history.gz")["sources"]
    excluded={k:set(v["families"]) for k,v in history.items()}
    def fingerprints(rows):
        return {digest(sorted(c["id"] for c in r["spec"]["deck"])) for r in rows}
    for name,key in (("train","train"),("dev","dev"),("reserve","train")):
        excluded["2a-"+name]=fingerprints(load(A/(name+".gz"))[key])
    for name in ("confirmation","dev-battles"):
        excluded["5g-"+name]=fingerprints(read(H.parent/f"m1-core5g/evidence/{name}.json"))
    for name in ("open","confirm"):
        excluded["5h-"+name]=fingerprints(load(H.parent/f"m1-core5h/evidence/{name}.gz"))
    excluded["6a-confirm"]=fingerprints(load(H.parent/"m1-core6a/evidence/confirm.gz"))
    excluded["6b1"]=set(r["family"] for r in read(H.parent/"m1-core6b1/evidence/panel.json")["roots"])
    excluded["core0"]=set()
    def opening(obj):
        if isinstance(obj,list):
            for x in obj:opening(x)
        if isinstance(obj,dict):
            if "deck" in obj and isinstance(obj["deck"],list) and obj["deck"] and isinstance(obj["deck"][0],dict):
                excluded["core0"].add(digest(sorted(c["id"] for c in obj["deck"])))
            else:
                for x in obj.values():opening(x)
    opening(read(H.parent/"m1-core1/benchmark.json"))
    assert excluded["core0"] and excluded["6b1"]<=excluded["6a-confirm"]
    banned=set.union(*excluded.values())
    assets=ROOT/"logs/m1-dc1-formal/roots"
    by_id={r["id"]:r for r in read(assets/"families.json")}
    role=next(c for c in read(assets/"catalog.json")["characters"] if c["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    donors=sorted(load(H.parent/"m1-core5d/evidence/panel.gz")["train"],key=lambda r:digest(["6a-donor",r["family"]]))
    mp={r["type"].upper() for r in read(H.parent/"m1-core6b1/evidence/native-mp.json")
        if r.get("method")=="get_MultiplayerConstraint" and r.get("il")=="172A"}
    jobs=[];used=set()
    for i in range(size):
        donor=by_id[donors[i%len(donors)]["family"]]
        rng=random.Random(digest(["6b2-deck",i]))
        while True:
            ids,rate=deck_for(role,cards,donor["spec"]["act"],donor["source"],donor["package"],rng)
            family=digest(sorted(ids))
            if ids and family not in banned and family not in used:break
        used.add(family);rng.shuffle(ids)
        deck=[dict(id=c,upgrade=int(cards[c]["upgradable"] and rng.random()<rate)) for c in ids]
        for j in range(2):
            spec=donor["spec"]|dict(deck=deck,seed=digest(["6b2-confirm",family,j])[:16].upper())
            jobs.append(dict(family=family,spec=spec,source=donor["source"],donor=donor["id"],
                             package=donor["package"],mp=sorted({c for c in ids if c.replace("_","") in mp})))
    assert len(used)==size and used.isdisjoint(banned) and len({r["spec"]["seed"] for r in jobs})==2*size
    with gzip.open(E/"confirm.gz","xt",encoding="utf8") as out:json.dump(jobs,out,separators=(",",":"))
    save(E/"panel-audit.json",dict(families=size,worlds=len(jobs),excluded=len(banned),
        sources={k:len(v) for k,v in excluded.items()},excluded_digest=digest(sorted(banned)),
        sources_new=Counter(r["source"] for r in jobs[::2]),mp=sum(bool(r["mp"]) for r in jobs[::2]),
        seconds=time.perf_counter()-start,sha256=sha(E/"confirm.gz")))
if __name__=="__main__":freeze(int(sys.argv[1]))
