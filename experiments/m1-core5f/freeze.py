"""Freeze composition-exclusive confirmation and stratified nested natural panels."""
import random
from collections import defaultdict
from common import *

def order(rows, meta, salt):
    # Interleave encounter/source/act strata by fractional within-stratum rank.
    groups = defaultdict(list)
    for r in rows:
        s = r["spec"]
        groups[s["act"], s["encounter"], meta[r["donor"]]["source"]].append(r)
    ranked = []
    for key, group in groups.items():
        shift = random.Random(digest([salt,key])).random()
        for i,r in enumerate(sorted(group,key=lambda x:digest([salt,x["family"]]))):
            ranked.append(((i+shift)/len(group),r["family"]))
    return [f for _,f in sorted(ranked)]

def main():
    pool = ROOT/"logs/m1-dc1-formal/roots"
    meta = {r["id"]:r for r in read(pool/"families.json")}
    banned = {composition(r["spec"]) for r in meta.values()}
    for path, groups in [("m1-core5d/evidence/panel.gz",None),("m1-core5d/evidence/augmentation.gz",None),
                         ("m1-core5e/evidence/panel.gz",None),("m1-core5b/evidence/panel.gz",["fresh"]),
                         ("m1-core5c/evidence/protocol.gz",["fresh"])]:
        panel = load(HERE.parent/path)
        for k in groups or panel:
            for r in panel[k]:
                banned.add(composition(r["spec"]))
    for group in load(HERE.parent/"m1-core5a/evidence/panels.gz").values():
        banned.update(composition(j[1]) for j in group)
    for filename in ("cohort.json.gz","capacity-cohort.json.gz"):
        p = load(H5/filename)
        banned.update(composition(r["spec"]) for k in ("open","train","bridge123") for r in p[k])
    role = next(r for r in read(pool/"catalog.json")["characters"] if r["name"]=="Ironclad")
    cards = {c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    panel = []
    donors = sorted(load(HERE.parent/"m1-core5d/evidence/panel.gz")["train"],key=lambda x:digest(["5f",x["family"]]))
    for row in donors[:96]:
        donor = meta[row["family"]]
        s = donor["spec"]
        rng = random.Random(digest(["5f-panel",donor["id"]]))
        while True:
            ids,rate = deck_for(role,cards,s["act"],donor["source"],donor["package"],rng)
            f = digest(sorted(ids))
            if ids and f not in banned: break
        banned.add(f)
        rng.shuffle(ids)
        deck = [dict(id=k,upgrade=int(cards[k]["upgradable"] and rng.random()<rate)) for k in ids]
        for j in range(2):
            panel.append(dict(family=f,spec=s|dict(deck=deck,seed=digest(["5f-world",f,j])[:16].upper())))
    save(E/"panel.json",panel)
    rows = []
    for edition in ("data","capacity"):
        rows.extend({k:r[k] for k in ("family","donor","spec")} for r in scan(H5/edition,split="train",kind="natural"))
    cond = {r["family"] for r in scan(H5/"data",split="train",kind="conditional")}
    assert len(cond)==56 and len({r["family"] for r in rows})==1041
    matched = cond.intersection(r["family"] for r in rows)
    dev = order([r for r in rows if r["family"] in matched],meta,"5f-dev-cond")[:12]
    dev += order([r for r in rows if r["family"] not in cond],meta,"5f-dev")[:96-len(dev)]
    train = order([r for r in rows if r["family"] not in dev],meta,"5f-scale")
    assert len(train)==945 and len(dev)==96
    save(E/"split.json",dict(dev=dev,train=train,conditional_only_train=sorted(cond-matched)))

if __name__=="__main__":main()
