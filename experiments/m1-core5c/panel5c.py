"""Freeze composition-exclusive families before any battle, preserving the 5B donor distribution."""
import sys, json, gzip, random, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-core5b"))
from panel import ROOT, FIVE, deck_for, digest, cohort, read
run_dir = os.environ.get("STS2_CORE5C_RUN")
E = (Path(run_dir).resolve() if run_dir else HERE) / "evidence"
OUT = (Path(run_dir).resolve() if run_dir else ROOT) / "logs/core5c"
HOST = Path(os.environ.get("STS2_CORE5C_HOST",ROOT/"logs/core5c-host")).resolve()
def freeze():
    a = json.load(gzip.open(FIVE / "evidence/panels.gz"))
    b = json.load(gzip.open(HERE.parent / "m1-core5b/evidence/panel.gz"))
    families = read(ROOT / "logs/m1-dc1-formal/roots/families.json")
    meta = {r["id"]: r for r in families}
    banned = {r["deck_family"] for r in families}
    for spec in [j[1] for j in a["confirm"]] + [j["spec"] for j in b["fresh"]]:
        banned.add(digest(sorted(c["id"] for c in spec["deck"])))
    role = next(r for r in read(ROOT / "logs/m1-dc1-formal/roots/catalog.json")["characters"] if r["name"] == "Ironclad")
    cards = {c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    fresh = []
    for j in sorted(a["train"], key=lambda j: digest(["5c-donor",j[3]])):
        donor = meta[j[3]]
        s = donor["spec"]
        if s["max_hp"] != 80:
            continue
        rng = random.Random(digest(["5c-deck",j[3]]))
        while True:
            names, rate = deck_for(role, cards, s["act"], donor["source"], donor["package"], rng)
            if names and digest(sorted(names)) not in banned:
                break
        banned.add(digest(sorted(names)))
        rng.shuffle(names)
        spec = s | dict(deck=[dict(id=n,upgrade=int(cards[n]["upgradable"] and rng.random()<rate)) for n in names])
        family = digest(spec)
        fresh.extend(dict(family=family,spec=spec|dict(seed=cohort.seed(family,"5c",i))) for i in range(2))
        if len(fresh)==96:
            break
    regression = sorted(b["fresh"],key=lambda w:digest(["5c-regression",w]))[:48]
    E.mkdir(parents=True,exist_ok=True)
    with gzip.open(E/"protocol.gz","xt") as f:
        json.dump(dict(fresh=fresh,regression=regression,arms=["base","medium","high","V2complete","V1complete"],
            primary="V2complete minus high, family-bootstrap lower 95% utility bound > 0 and wins >= high; all 96 paired outcomes required",
            gates="frozen weights, full known mass, +1 utility; retain baseline otherwise"),f)
if __name__=="__main__":
    freeze()
