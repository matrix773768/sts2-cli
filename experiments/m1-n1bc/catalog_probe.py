"""Probe N1A on normal-size authored mixed decks, independently of HotDraw search eligibility."""
from collections import Counter
import gzip
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from arena import ROOT, checksum, manifest


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    build=ROOT/"logs/hotdraw-mechanism-build-03/build.json"
    identity=json.loads(build.read_bytes())
    for key,label in (("dll","harness"),("solver","solver"),("runtime","runtime")):
        if checksum(Path(identity[key]))!=identity[label+"_sha256"]:
            raise ValueError(key)
    tree=build.parent/("CombatSolver-"+identity["upstream"])
    base=json.loads((ROOT/"logs/hotdraw-mechanism-final/TEST_SUBJECT_BOSS/request.json").read_bytes())
    used, seen, rows = set(), set(), []
    jobs=[j for j in manifest()["jobs"] if j[2]=="train"]
    start=perf_counter()
    for i in range(32):
        candidates=[j for j in jobs if j[1]["encounter"] not in used]
        j=max(candidates,key=lambda j:len({c["id"] for c in j[1]["deck"]}-seen))
        _,spec,_,family,_=j
        used.add(spec["encounter"])
        seen.update(c["id"] for c in spec["deck"])
        path=out/f"{i:02}"
        path.mkdir()
        req=base | dict(encounterId=spec["encounter"],scenarioId=f"N1BC-CATALOG-{i}",
                        initialPlayerHp=spec["hp"],initialPlayerMaxHp=spec["max_hp"],
                        cards=[dict(cardId=c["id"],upgradeLevels=c["upgrade"],count=1,
                                    pile="Hand" if idx<5 else "Draw") for idx,c in enumerate(spec["deck"])])
        (path/"request.json").write_text(json.dumps(req))
        args=[identity["runtime"],identity["dll"],"--hotdraw","mechanisms",
              str((path/"request.json").resolve()),str((path/"export.json").resolve())]
        try:
            with (path/"run.log").open("wb") as f:
                proc=subprocess.run(args,cwd=tree,stdout=f,stderr=subprocess.STDOUT,timeout=35)
            ok=proc.returncode==0
        except subprocess.TimeoutExpired:
            ok=False
        rows.append(dict(ordinal=i,family=family,encounter=spec["encounter"],cards=len(spec["deck"]),ok=ok))
    graphs, cards, conflicts = {}, {}, set()
    reasons=Counter()
    for row in rows:
        path=out/f"{row['ordinal']:02}"
        if not row["ok"]:
            lines=(path/"run.log").read_text(errors="replace").splitlines()
            row["reason"]=next((s[:400] for s in lines if "Exception" in s),"export_failed_or_timeout")
            reasons[row["reason"]]+=1
            continue
        data=json.loads((path/"export.json").read_bytes())["result"]
        row["fairness"]=data["fairness"]
        row["warm_ms"]=data["meanMilliseconds"]
        for card in data["input"]["cardRules"]:
            name=card["Entry"]
            # Keep only stable named fields, omitting interpreter-local numeric references.
            value={k:card[k] for k in ("Type","Target","BaseCost","UpgradedCost","HookMask","OrderedVarNames",
                                       "coverage","CanGenerateUnknown","knownCustomSemantics")}
            value["operations"]=[(op["Op"],op["Flags"]) for op in card["operations"]]
            if name in cards and cards[name]!=value:
                conflicts.add(name)
            cards[name]=value
        for enemy in data["input"]["enemyRules"]:
            if not enemy["rules"]:
                continue
            name=enemy["Entry"]
            value=[{k:node[k] for k in ("MoveId","NodeKind","next","targets","ConditionalKind",
                                         "condition","MustPerformOnceBeforeRepeat","CannotRepeat")}
                   for node in enemy["rules"]["nodes"]]
            if name in graphs and graphs[name]!=value:
                conflicts.add(name)
            graphs[name]=value
    for name in conflicts:
        graphs.pop(name,None)
        cards.pop(name,None)
    summary=dict(seconds=perf_counter()-start,build_sha256=checksum(build),rows=rows,failures=reasons,
                 conflicting=sorted(conflicts),cards=cards,graphs=graphs)
    with gzip.open(out/"catalog.json.gz","wt",encoding="utf-8") as f:
        json.dump(summary,f,separators=(",",":"))


if __name__=="__main__":
    run(Path(sys.argv[1]))
