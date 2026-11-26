"""Fill observed gaps in the N1BC static catalogue with the frozen N1A mechanisms exporter."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
from time import perf_counter

from build import HERE,ROOT,sha


def run(out,panel):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    identity_file=ROOT/"logs/hotdraw-mechanism-build-03/build.json"
    identity=json.loads(identity_file.read_bytes())
    for key,label in (("dll","harness"),("solver","solver"),("runtime","runtime")):
        if sha(Path(identity[key]))!=identity[label+"_sha256"]: raise ValueError(key)
    catalog=json.loads(gzip.decompress((HERE.parent/"m1-n1bc/catalog.json.gz").read_bytes()))
    template=json.loads((ROOT/"logs/hotdraw-mechanism-final/TEST_SUBJECT_BOSS/request.json").read_bytes())
    wanted_cards=set()
    enemies_by_encounter={}
    for r in json.loads((panel/"panel.json").read_bytes())["rows"]:
        data=json.loads(gzip.decompress((panel/(r["family"]+".json.gz")).read_bytes()))
        for q in data["queries"]:
            c=q.get("observed_c")
            if not c: continue
            enemies_by_encounter.setdefault(r["encounter"],set()).update(e["species"] for e in c["enemies"])
            for zone in ("hand","deck","discard","exhaust"):
                wanted_cards.update(card["id"] for card in c[zone])
            wanted_cards.update(k.rsplit("#",1)[0] for k in c["belief"]["counts"])
    wanted_cards-=catalog["cards"].keys()
    wanted_enemies=set.union(*enemies_by_encounter.values())-catalog["graphs"].keys()
    rows=[]
    result=dict(cards={},graphs={})
    conflicts=set()
    def register(group,name,value):
        prior=result[group].setdefault(name,value)
        if prior!=value: conflicts.add((group,name))
    for encounter,enemies in sorted(enemies_by_encounter.items()):
        if not enemies & wanted_enemies and (not wanted_cards or rows):continue
        job=out/encounter
        job.mkdir()
        req=template|dict(encounterId=encounter,scenarioId="CORE1R2-RULES-"+encounter)
        req["cards"]=[*template["cards"],*(dict(cardId=c,pile="Discard",upgradeLevels=0,count=1) for c in sorted(wanted_cards))]
        path=job/"request.json"
        path.write_text(json.dumps(req))
        export=job/"export.json"
        with (job/"run.log").open("wb") as log:
            p=subprocess.run([identity["runtime"],identity["dll"],"--hotdraw","mechanisms",str(path.resolve()),str(export.resolve())],
                cwd=identity_file.parent/("CombatSolver-"+identity["upstream"]),stdout=log,stderr=subprocess.STDOUT,timeout=35)
        rows.append(dict(encounter=encounter,exit_code=p.returncode))
        if p.returncode: continue
        rules=json.loads(export.read_bytes())["result"]["input"]
        for card in rules["cardRules"]:
            if card["Entry"] not in wanted_cards:continue
            value={k:card[k] for k in ("Type","Target","BaseCost","UpgradedCost","HookMask","OrderedVarNames","coverage","CanGenerateUnknown","knownCustomSemantics")}
            value["operations"]=[[o["Op"],o["Flags"]] for o in card["operations"]]
            register("cards",card["Entry"],value)
        for enemy in rules["enemyRules"]:
            if enemy["Entry"] not in wanted_enemies or not enemy["rules"]:continue
            register("graphs",enemy["Entry"],[{k:n[k] for k in ("MoveId","NodeKind","next","targets","ConditionalKind","condition","MustPerformOnceBeforeRepeat","CannotRepeat")}
                for n in enemy["rules"]["nodes"]])
    for group,name in conflicts: result[group].pop(name,None)
    result.update(build_sha256=sha(identity_file),rows=rows,conflicts=sorted(conflicts),
        missing_cards=sorted(wanted_cards-result["cards"].keys()),missing_graphs=sorted(wanted_enemies-result["graphs"].keys()))
    (out/"rules.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    (out/"timing.json").write_text(json.dumps(dict(seconds=perf_counter()-start)))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("out",type=Path)
    parser.add_argument("panel",type=Path)
    args=parser.parse_args()
    run(args.out,args.panel)
