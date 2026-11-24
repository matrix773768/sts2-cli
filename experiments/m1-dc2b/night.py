"""Checks and finite plan derivation for the first DC2B night."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil

from value import ROOT, torch, load
from dc_common import read, checksum, write_json
from dc_metrics import paired, ledger

INITIAL=ROOT/"logs/inf1/jobs/dc2b-initial"
TEMPLATE=ROOT/"configs/training_jobs/dc2b-curriculum.json"
SLOTS=32
GENERATIONS=12
STOP_RESERVE=180


def initial():
    from tools.training_manager.dashboard.backend import review_gate
    from tools.training_manager.common import HOME
    from tools.training_manager.manager import Manager
    from tools.training_manager.ledger import identity
    blocked=review_gate(Manager(HOME))
    if blocked:
        raise ValueError(blocked)
    final=INITIAL/"initial"
    _,best=load(final/"best.pt")
    saved=torch.load(final/"resume.pt",weights_only=True,map_location="cpu")
    if (saved["done"]!=4096 or not saved["optimizer"]["state"] or
        any(not torch.equal(best["model"][k],v) for k,v in saved["model"].items()) or
        best["policies"]!=saved["policies"]):
        raise ValueError("G0 weights and optimizer commit disagree")
    data={name:identity(INITIAL/name/"ledger/results.sqlite")
          for name in ("development","complex-development","complex-baseline")}
    if (data["complex-development"]["count"]!=342 or data["complex-baseline"]["count"]!=342 or
        data["complex-development"]["manifest"]!=data["complex-baseline"]["manifest"]):
        raise ValueError("Complex development cohorts disagree")
    initial_count=len(set(best["policies"]))
    if initial_count!=len(best["policies"]) or initial_count+2*GENERATIONS>best["spec"]["policy_slots"]:
        raise ValueError("Policy slots do not support twelve generations")
    return dict(initial_slots=initial_count,capacity=best["spec"]["policy_slots"],best=checksum(final/"best.pt"),
                resume=checksum(final/"resume.pt"),updates=saved["done"],evaluations=data)


def finite(item):
    if isinstance(item,float):
        return math.isfinite(item)
    if isinstance(item,dict):
        return all(finite(v) for v in item.values())
    if isinstance(item,list):
        return all(finite(v) for v in item)
    return True


def audit(out,generation):
    root=out.parent
    prefix=f"g{generation}"
    fit=root/f"{prefix}-fit"
    _,best=load(fit/"best.pt")
    saved=torch.load(fit/"resume.pt",weights_only=True,map_location="cpu")
    valid=read(fit/"update-01600.json")
    expected=initial()["initial_slots"]+2*generation
    from tools.training_manager.ledger import identity as ledger_identity
    for state in saved["optimizer"]["state"].values():
        if any(torch.is_tensor(t) and not torch.isfinite(t).all() for t in state.values()):
            raise ValueError("Nonfinite optimizer checkpoint")
    parent=INITIAL/"initial/best.pt" if generation==1 else root/f"g{generation-1}-fit/best.pt"
    _,parent_model=load(parent)
    production={}
    observed_seeds=set()
    for arm,target,limit in (("direct",8000,8704),("search",2000,2176)):
        base=root/f"{prefix}-{arm}"
        summary=read(base/"ledger/summary.json")
        cache=root/f"{prefix}-{arm}-cache"
        cached=read(cache/"manifest.json")
        identity=cached["policy"]
        for descriptors in cached["shards"].values():
            for d in descriptors:
                if checksum(cache/d["name"])!=d["sha256"]:
                    raise ValueError("Cache shard checksum mismatch")
        evidence=ledger_identity(base/"ledger/results.sqlite")
        if evidence["model"]!=checksum(parent) or evidence["manifest"]!=checksum(base/"roots.json") or evidence["count"]!=summary["attempts"]:
            raise ValueError("Production identity mismatch")
        if (not target<=summary["complete"]<=summary["attempts"]<=limit or identity not in best["policies"]
            or summary["status"].get("error",0) or summary["counts"].get("terminal_mismatch",0)):
            raise ValueError(f"Invalid {arm} production")
        plan=read(base/"roots.json")
        for _,spec,split,family,_ in plan["jobs"]:
            wanted="validation" if int(family[:8],16)%7==0 else "train"
            if split!=wanted or spec["seed"] in observed_seeds:
                raise ValueError("Invalid world or family split")
            observed_seeds.add(spec["seed"])
        production[arm]=dict(summary=summary,policy=identity,categories=plan["categories"],
                             diagnostic=len(plan["diagnostic"]),promotion=read(base/"promotion.json"))
    if set(best["policies"])-set(parent_model["policies"])!={p["policy"] for p in production.values()}:
        raise ValueError("Generation changed an existing behavior identity")
    if (saved["done"]!=1600 or len(set(best["policies"]))!=expected
            or best["policies"]!=saved["policies"] or not finite(valid)
            or any(not torch.isfinite(t).all() or not torch.equal(t,saved["model"][k]) for k,t in best["model"].items())):
        raise ValueError("Nonfinite metrics or mismatched generation checkpoint")
    reports={}
    severe,weak=False,False
    previous=[read(root/f"g{i}-audit/summary.json") for i in range(1,generation)]
    for arm in ("development","complex"):
        local=root/f"{prefix}-{arm}"
        original=INITIAL/("development" if arm=="development" else "complex-development")
        lid=ledger_identity(local/"ledger/results.sqlite")
        ref_id=ledger_identity(original/"ledger/results.sqlite")
        if lid["model"]!=checksum(fit/"best.pt") or lid["manifest"]!=ref_id["manifest"] or lid["count"]!=ref_id["count"]:
            raise ValueError("Evaluation model or root manifest differs")
        now=ledger(local/"ledger")
        ref=ledger(original/"ledger")
        if now.keys()!=ref.keys() or not now:
            raise ValueError("Development membership differs")
        current=read(local/"ledger/summary.json")
        good=max(previous,key=lambda r:(r["evaluation"][arm]["summary"]["win_rate"],r["generation"]),default=None)
        if good and good["evaluation"][arm]["summary"]["win_rate"]>read(original/"ledger/summary.json")["win_rate"]:
            preferred=ledger(root/f"g{good['generation']}-{arm}"/"ledger")
        else:
            preferred=ref
        tests=[paired(((r[i],now[i]) for i in now),bootstrap=True) for r in (ref,preferred)]
        severe|=any(t["death_delta"]>=.10 or t["win_delta"]<=-.12 or
                    t["joint_complete"]<.96*len(now) for t in tests)
        weak|=any(t["death_delta"]>=.05 or t["win_delta"]<=-.06 for t in tests)
        reports[arm]=dict(summary=current,by_hp=read(local/"metrics.json"),versus=tests)
    stop=severe or (generation>=3 and weak and previous[-1]["weak"])
    durations={}
    for name in ("direct","search","direct-cache","search-cache","fit","development","complex"):
        results=(root/f"{prefix}-{name}"/"attempts").glob("*/result.json")
        durations[name]=sum(max(0,r["ended"]-r["started"]) for path in results for r in [read(path)])
    sampling=read(fit/"sampling.json")
    if sum(sampling["realized_rows"].values())!=1600*512:
        raise ValueError("Sample accounting does not match committed training updates")
    result=dict(generation=generation,complete=True,stop=stop,weak=weak,severe=severe,production=production,
                validation=valid,evaluation=reports,seconds=durations,updates=1600,
                latest=str(fit/"best.pt"),sha256=checksum(fit/"best.pt"),
                sampling=sampling)
    write_json(out/"summary.json",result)
    return 3 if stop else 0


def finish_budget(out,generation):
    request=out/"request.json"
    remaining=read(request)["remaining"] if request.exists() else None
    previous=[read(out.parent/f"g{i}-audit/summary.json") for i in range(1,generation)]
    estimate=max([12*60]+[sum(r["seconds"].get(k,0) for k in ("fit","development","complex"))
                           for r in previous[-3:]])
    required=math.ceil(1.20*estimate)+STOP_RESERVE
    insufficient=remaining is not None and remaining<required
    projected=max((sum(r["seconds"].values()) for r in previous[-3:]),default=None)
    write_json(out/"summary.json",dict(remaining=remaining,required=required,projected_next_generation=projected,
                                     decision="preserve_experience" if insufficient else "train_and_evaluate"))
    return 3 if insufficient else 0


def make(path):
    doc=read(TEMPLATE)
    originals=doc["stages"]
    stages=[dict(id="preflight",depends_on=[],args=["experiments/m1-dc2b/night.py","initial"],
                 gpu=False,heavy=False,workers=1,resume="restart",boundary="Audit G0 and policy slot capacity")]
    for g in range(1,GENERATIONS+1):
        prefix=f"g{g}"
        source=min(g,3)
        for item in originals:
            if not item["id"].startswith(f"g{source}-"):
                continue
            s=json.loads(json.dumps(item))
            if g>3:
                for key in ("id","args","depends_on"):
                    value=s[key] if isinstance(s[key],list) else [s[key]]
                    value=[re.sub(r"g([123])-",lambda m:f"g{int(m[1])+g-3}-",v) for v in value]
                    s[key]=value if key!="id" else value[0]
            args=s["args"]
            if "produce" in args:
                args[args.index("--generation")+1]=str(g)
                args[args.index("--chunk")+1]="128"
                args+=["--night-history"]
                if g==1:
                    s["depends_on"]=["preflight"]
                if g>1:
                    args[args.index("--previous")+1]=str(g-1)
                    s["depends_on"]=[f"g{g-1}-audit"]
            if s["id"]==prefix+"-fit":
                at=args.index("--extra")
                args[at:]=["--night-replay","--extra",*[f"{{output}}/g{i}-{arm}-cache"
                                for i in range(g,0,-1) for arm in ("direct","search")]]
                stages.append(dict(id=prefix+"-budget",depends_on=s["depends_on"],args=[
                    "experiments/m1-dc2b/night.py","budget","{work}",str(g)],gpu=False,
                    heavy=False,workers=1,resume="restart",boundary="Budget admission"))
                s["depends_on"]=[prefix+"-budget"]
            stages.append(s)
        stages.append(dict(id=prefix+"-audit",depends_on=[prefix+"-complex"],args=[
            "experiments/m1-dc2b/night.py","audit","{work}",str(g)],gpu=False,heavy=True,
            workers=2,resume="restart",boundary="Completed generation evidence"))
    doc.update(id="dc2b-night1",name="DC2B 八小时夜间训练",output="logs/inf1/jobs/dc2b-night1",
               budget_seconds=28800,stop_grace_seconds=STOP_RESERVE,budget_reserve_seconds=STOP_RESERVE,stages=stages)
    doc["limits"].update(generations=12,experience_roots=120000,experience_attempts=130560,
                         optimizer_updates=19200,direct_per_generation=8000,search_per_generation=2000)
    doc["inputs"]+=["tools/training_manager/manager.py","experiments/m1-dc2b/night.py","logs/inf1/jobs/dc2b-initial/initial/resume.pt",
                    *[f"logs/inf1/jobs/dc2b-initial/{name}/ledger/results.sqlite"
                      for name in ("development","complex-development","complex-baseline")]]
    path.write_bytes((json.dumps(doc,indent=2,ensure_ascii=False)+"\n").encode())


def recoverable(source):
    jobs=ROOT/"logs/inf1/jobs"
    source=source.resolve()
    if source.parent!=jobs or not re.fullmatch(r"dc2b-night1(?:-r[0-9]+)?",source.name):
        raise ValueError("Only a terminal DC2B night job can be continued")
    report=read(source/"report.json")
    if report["id"]!=source.name:
        raise ValueError("Continuation source ID mismatch")
    if report["state"]=="cancelled" and report["reason"]=="budget":
        return report
    current=report.get("current_stage")
    if isinstance(current,dict):
        current=current["id"]
    if (report["state"]=="failed" and isinstance(current,str) and current.endswith("-budget")
            and read(source/current/"summary.json")["decision"]=="preserve_experience"):
        return report
    raise ValueError("Only budget stops may be continued automatically")


def assets(source):
    for stage in sorted(source.glob("g*-*")):
        if not stage.is_dir() or not re.fullmatch(r"g[0-9]+-[a-z-]+",stage.name):
            continue
        keep={"roots.json","promotion.json","manifest.json","progress.json","metrics.json",
              "sampling.json","summary.json","best.pt","resume.pt"}
        for path in sorted(stage.iterdir()):
            if path.is_file() and (path.name in keep or path.suffix==".npz" or path.name.startswith("update-")):
                yield path
        for name in ("summary.json","results.sqlite","results.sqlite-wal"):
            path=stage/"ledger"/name
            if path.is_file():
                yield path
        yield from (stage/"attempts").glob("*/result.json")


def continuation(source,destination,key,seconds):
    report=recoverable(source)
    source=source.resolve()
    if not re.fullmatch(r"dc2b-night1-r[0-9]+",key) or key==source.name or seconds<=STOP_RESERVE:
        raise ValueError("Choose a new continuation ID and a positive budget above the reserve")
    plan=read(source/"task.json")
    for path in ("experiments/m1-dc2b/fit.py","experiments/m1-dc2b/stages.py",
                 "experiments/m1-dc2b/battle.py","experiments/m1-dc2b/value.py","experiments/m1-dc2b/night.py"):
        if plan["inputs"].get(path)!=checksum(ROOT/path):
            raise ValueError(f"Original continuation code changed: {path}")
    done={r["stage"] for r in report["runs"] if (r.get("outcome") or {}).get("state")=="completed"
          and (r.get("outcome") or {}).get("exit_code")==0}
    stages=[s for s in plan["stages"] if s["id"] not in done and s["id"]!="restore"]
    if not stages:
        raise ValueError("No uncompleted stages")
    restore=dict(id="restore",depends_on=[],args=["experiments/m1-dc2b/night.py","restore",
                   source.relative_to(ROOT).as_posix(),"{output}"],gpu=False,heavy=False,workers=1,
                 resume="restart",boundary="Copy committed artifacts to independent output")
    for s in stages:
        s["depends_on"]=["restore",*[k for k in s["depends_on"] if k not in done and k!="restore"]]
    fresh=read(ROOT/"configs/training_jobs/dc2b-night1.json")
    listed={p.relative_to(ROOT).as_posix() for p in assets(source)}
    fresh.update(id=key,name=key,output=f"logs/inf1/jobs/{key}",budget_seconds=seconds,
                 stages=[restore,*stages],inputs=sorted(set(fresh["inputs"])|listed))
    with destination.open("x",encoding="utf-8") as stream:
        json.dump(fresh,stream,indent=2,ensure_ascii=False)


def restore(source,destination):
    recoverable(source)
    root=destination.resolve()
    if root.parent!=ROOT/"logs/inf1/jobs" or not re.fullmatch(r"dc2b-night1-r[0-9]+",root.name):
        raise ValueError("Continuation destination is outside the admitted job scope")
    for path in assets(source.resolve()):
        target=root/path.relative_to(source.resolve())
        target.parent.mkdir(parents=True,exist_ok=True)
        if path.name=="progress.json":
            info=read(path)
            if info.get("checkpoint"):
                info["checkpoint"]=str(root/Path(info["checkpoint"]).relative_to(source.resolve()))
            if target.exists() and read(target)!=info:
                raise ValueError(f"Restored progress differs: {target}")
            if not target.exists():
                write_json(target,info)
            continue
        if target.exists():
            if checksum(target)!=checksum(path):
                raise ValueError(f"Restored artifact differs: {target}")
            continue
        temporary=target.with_suffix(target.suffix+".restore")
        shutil.copyfile(path,temporary)
        temporary.replace(target)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("make","initial","audit","budget","continue","restore"))
    parser.add_argument("path",type=Path,nargs="?")
    parser.add_argument("generation",nargs="?")
    parser.add_argument("--id")
    parser.add_argument("--seconds",type=int,default=28800)
    args=parser.parse_args()
    if args.mode=="initial":
        print(json.dumps(initial(),ensure_ascii=False))
    elif args.mode=="make":
        make(args.path)
    elif args.mode=="continue":
        continuation(args.path,Path(args.generation),args.id,args.seconds)
    elif args.mode=="restore":
        restore(args.path,Path(args.generation))
    else:
        args.path.mkdir(parents=True,exist_ok=True)
        raise SystemExit((audit if args.mode=="audit" else finish_budget)(args.path,int(args.generation)))
