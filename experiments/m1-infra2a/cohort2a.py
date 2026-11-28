"""Freeze composition-exclusive families from opening manifests only."""
import gzip
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = ROOT.parent / "sts2-cli"
sys.path.insert(0, str(ROOT / "experiments/m1-core5d"))
from panel5d import deck_for, digest
sys.path.insert(0, str(ROOT / "engine/HotSearch"))
sys.modules.pop("experience", None)
from experience import require, sha

def read(path):
    return json.load((gzip.open if path.suffix == ".gz" else open)(path, "rb"))

def save(path, obj):
    with path.open("xb") as f, gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as g:
        g.write(json.dumps(obj, separators=(",", ":")).encode())

def main():
    require(subprocess.check_output(["git","rev-parse","HEAD"],cwd=CORE,text=True).strip()
            == "0902c56e338e72a4e7f97ef5e9617151a909c91c","CORE checkout")
    sources = {}
    banned = set()
    def exclude(path, specs):
        fingerprints = sorted({digest(sorted(c["id"] for c in s["deck"])) for s in specs})
        sources[path.name+"@"+path.parent.parent.name] = dict(sha256=sha(path), families=fingerprints)
        banned.update(fingerprints)
    assets = CORE/"logs/m1-dc1-formal/roots"
    path = assets/"families.json"
    meta = {r["id"]:r for r in read(path)}
    exclude(path, [r["spec"] for r in meta.values()])
    for name in ["m1-core4/evidence/panels.json.gz","m1-core5a/evidence/panels.gz",
                 "m1-core5b/evidence/panel.gz","m1-core5c/evidence/protocol.gz",
                 "m1-core5d/evidence/panel.gz","m1-core5d/evidence/augmentation.gz",
                 "m1-core5e/evidence/panel.gz","m1-core5f/evidence/panel.json",
                 "m1-infra1h4/evidence/open-specs.json","m1-infra1h5/cohort.json.gz",
                 "m1-infra1h5/capacity-cohort.json.gz"]:
        path=(ROOT if "infra" in name else CORE)/"experiments"/name
        specs=[]
        def visit(v):
            if isinstance(v,dict):
                if "deck" in v and "encounter" in v: specs.append(v)
                else:
                    for val in v.values(): visit(val)
            elif isinstance(v,list):
                for val in v: visit(val)
        visit(read(path))
        require(specs,name)
        exclude(path,specs)
    old = read(CORE/"experiments/m1-core5f/evidence/split.json")
    require(set(old["train"]+old["dev"]) <= banned,"missing H5 families")
    save(HERE/"history.gz",dict(sources=sources,core5f=old))
    role=next(r for r in read(assets/"catalog.json")["characters"] if r["name"]=="Ironclad")
    cards={c["id"]:c for c in role["cards"] if c["id"] not in {"DEMONIC_SHIELD","TAG_TEAM","TANK"}}
    base=read(CORE/"experiments/m1-core5d/evidence/panel.gz")["train"]
    for edition,count,split in [("dev",192,"dev"),("train",3400,"train"),("reserve",128,"train")]:
        donors=sorted(base,key=lambda r:digest(["2a",edition,r["family"]]))
        rows=[]
        for i in range(count):
            d=meta[donors[i%len(donors)]["family"]]
            rng=random.Random(digest(["2a",edition,i]))
            while True:
                names,rate=deck_for(role,cards,d["spec"]["act"],d["source"],d["package"],rng)
                f=digest(sorted(names))
                if names and f not in banned: break
            banned.add(f)
            rng.shuffle(names)
            deck=[dict(id=n,upgrade=int(cards[n]["upgradable"] and rng.random()<rate)) for n in names]
            rows.append(dict(family=f,donor=d["id"],source=d["source"],spec=d["spec"]|dict(deck=deck,seed=digest(["2a-world",f])[:16].upper())))
        save(HERE/(edition+".gz"),{split:rows,"protocol":dict(version="m1-infra2a-v1",split=split,edition=edition,history=sha(HERE/"history.gz"),order="generation order, cycling hash-ordered 5D train donors",reserve="activate only below 3151 eligible primary training families",target=3151)})
if __name__=="__main__": main()
