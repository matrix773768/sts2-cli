"""Aggregate full paired roots, censored results, repeated-world errors and actual policy switches."""
import json,math
from collections import defaultdict
from statistics import mean
from time import perf_counter
from panel5e import E,load,rows
from metrics5b import stats,paired,ci
from data5e import completed,deltas,read_cases
from reliability5e import old_location

def arm(group,name):
    return sorted([r for f in E.glob(group+"-"+name+"-*.gz") for r in rows(f)],key=lambda r:r["i"])
def measure(rs):
    result=stats(rs);result["reached_seconds"]=sum(r["seconds"] for r in rs)
    qs=[q for r in rs for q in r["queries"]]
    if any("incumbent" in q for q in qs):
        result.update(incumbent_available=sum(q["incumbent_available"] for q in qs),
                      incumbent_G2=sum(q["incumbent"]=="G2" for q in qs),
                      generation_switch=sum(q["generation_switch"] for q in qs),
                      switch_from_G2=sum(q["generation_switch"] and q["incumbent"]=="G2" for q in qs))
    return result
def group_result(group,names,repair=False):
    data={k:arm(group,k) for k in names}
    if repair:
        replacements={k:{r["i"]:r for r in arm("repair",k)} for k in names}
        bad={r["i"] for rs in data.values() for r in rs if not r["terminal"]}
        for name,rs in data.items():
            if bad-replacements[name].keys():raise ValueError(("Missing paired repair",name,bad))
            data[name]=[replacements[name][r["i"]] if r["i"] in bad else r for r in rs]
    ident=lambda rs:[(r["family"],r["seed"]) for r in rs]
    assert all(ident(rs)==ident(data[names[0]]) for rs in data.values())
    expected=[(w["family"],w["spec"]["seed"]) for w in load(E/"panel.gz")[group]]
    if ident(data[names[0]])!=expected:raise ValueError("Paired panel is missing or out of order")
    return {name:measure(rs)|dict(versus={k:paired(rs,b) for k,b in data.items() if k!=name}) for name,rs in data.items()}
def followup_result():
    prior={r["i"]:r for r in read_cases("train") if completed(r)}
    checks=[]
    for f in E.glob("audit12-train-*.gz"):
        for case in rows(f):
            r=prior[case["i"]];pilot=deltas(r)
            if not completed(case):
                checks.append(dict(i=case["i"],error=case.get("error") or "incomplete"));continue
            ref=deltas(case)
            checks.append(dict(i=case["i"],family=r["family"],pilot=mean(pilot),original_world=pilot[0],old=old_location(pilot),
                       reference=mean(ref),worlds=len(ref),zero_control=not any(pilot),nonzero_reference=any(ref),
                       v2=r["plans"][0]["v2"]-r["plans"][1]["v2"]))
    valid=[r for r in checks if "error" not in r];noisy=[r for r in valid if not r["zero_control"]]
    return dict(cases=checks,n=len(valid),noisy=len(noisy),rmse={
        k:math.sqrt(mean((r[k]-r["reference"])**2 for r in noisy)) for k in ("original_world","old","pilot","v2")} if noisy else {})

def conditional_errors():
    fit=json.loads((E/"fit.json").read_bytes())
    cases=[r for r in read_cases("dev") if completed(r)]
    scores={"V2":fit["epoch0"]["predictions"]}
    for name in ("mc","td"):
        scores[name]=fit[name]["curve"][fit[name]["winner"]-1]["predictions"]
    comparisons={}
    for a,b in (("td","mc"),("td","V2"),("mc","V2")):
        families=defaultdict(list)
        for case,x,y in zip(cases,scores[a],scores[b],strict=True):
            target=mean(deltas(case))
            families[case["family"]].append((x-target)**2-(y-target)**2)
        comparisons[a+"-"+b]=ci([mean(v) for v in families.values()])
    return comparisons
def run():
    start=perf_counter()
    choice=json.loads((E/"selection.json").read_bytes());name=choice["challenger"]
    report=dict(selection=group_result("selection",["V2","mc","td","anchor-"+name]),
                confirm=group_result("confirm",["V2",name,"V2low"]),followup=followup_result(),
                paired_development_mse=conditional_errors())
    report["paired_repair"]=group_result("confirm",["V2",name,"V2low"],True)
    report["cost"]={k:dict(roots=len(arm("cost",k)),worker_seconds=json.loads((E/f"cost-{k}-0.time.json").read_bytes()))
                    for k in ("V2",name) if (E/f"cost-{k}-0.time.json").exists()}
    if (E/"native.time.json").exists():
        native=list(rows(E/"native.gz"))
        report["native"]={k:dict(episodes=sum(r["arm"]==k for r in native),
            matched=sum(r.get("match",False) for r in native if r["arm"]==k),
            cost_matched=sum(r.get("match",False) for r in native if r["arm"]==k and r["cost_root"]),
            flips=[r for r in native if r["arm"]==k and r["flip"]]) for k in ("V2",name)}
    report["seconds"]=perf_counter()-start
    (E/"results.json").write_text(json.dumps(report,indent=2))
if __name__=="__main__":run()
