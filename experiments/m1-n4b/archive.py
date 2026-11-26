"""Pack only qualified production rows and selected models. Retain the superseded native failure separately."""
from pathlib import Path
import json
import sys
from design import BUILD,HERE,LOGS,cohort,read
from pack import write_zip


def archive(out):
    res=read(out/"results.json.gz")
    raw=[BUILD/"build.json",LOGS/"n4b-plan.json"]
    raw.extend(p for p in (LOGS/"n4b-host/build.json",LOGS/"n4b-native/checks.json") if p.exists())
    models=[]
    fit=LOGS/"n4b-finalfit"
    selection=read(fit/"selection.json")
    names=selection["curves"]
    for name in names:
        models.append(fit/f"{name}-{selection['epoch']}.pt")
    assert len(models)==8
    raw.extend([fit/"result.json",fit/"selection.json"])
    for pattern in ("n4b-finalcore-*","n4b-finalmenu-*","n4b-natural-final","n4b-matched","n4b-native-final",
                    "n4b-zeros","n4b-battle-*","n4b-deployment-native","n4b-flip"):
        for d in LOGS.glob(pattern):
            raw.extend(d.glob("*.json"))
            raw.extend(d.glob("*.json.gz"))
    costs={}
    for p in sorted(LOGS.glob("n4b-*/run.json")):
        costs[p.parent.name]=read(p)["seconds"]
    for directory,file in [("n4b-fit","result.json"),("n4b-finalfit","result.json"),("n4b-native","checks.json"),
        ("n4b-native-final","checks.json"),("n4b-zeros","zeros.json.gz"),("n4b-deployment-native","native.json")]:
        p=LOGS/directory/file
        if p.exists():
            costs[directory]=read(p)["seconds"]
    costs["endpoint_fit"]=read(LOGS/"n4b-plan.json")["seconds"]
    costs["analysis"]=res["analysis_seconds"]
    outputs={}
    for name,paths in [("raw.zip",raw),("models.zip",models)]:
        p=out/name
        write_zip(p,paths)
        outputs[name]=dict(sha256=cohort.checksum(p),bytes=p.stat().st_size,entries=len(set(paths)))
    result=dict(version="n4b.turn2.v2",parent=cohort.PARENT_SHA,solver=read(BUILD/"build.json")["artifacts"]["solver-bin/CombatSolver.dll"],
        selected_epoch=selection["epoch"],arms={p.name:cohort.checksum(p) for p in models},archives=outputs,
        seconds_by_task=costs,measured_seconds_sum=sum(costs.values()),coverage=res["coverage"],teacher=res["teacher"],
        unit_gain=res["unit_gain"],paired_noise=res["paired_noise"],
        learning={k:{a:b for a,b in v.items() if a!="shifts"} for k,v in res["learning"].items()},
        combat={k:{a:b for a,b in v.items() if a!="counts"} for k,v in res["battles"]["arms"].items()})
    with (out/"summary.json").open("x",encoding="utf8") as f:
        json.dump(result,f,indent=2,allow_nan=False)


if __name__=="__main__":
    archive(Path(sys.argv[1]))
