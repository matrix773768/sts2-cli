"""Write a portable ledger of inputs, manifests, assignments, world witnesses and outputs."""
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from time import perf_counter
import json
import sys
from pilot_protocol import LOGS, cohort, design, jobs, read, write
from assess import load_rows, one

CORE=("core-a","core-b","repair","mixcore","mixrepair","mixall","mixallrepair","multi","mixallmulti","multiext")
RUNS=("dev","dev1","dev2","devrepair","multi-dev","replay","replay-dev",*CORE,"replicate",
      "cap-probe","stress","timing","native","native-loss","nativemulti")
FILES=("mix","mix-verify","curve","dev-analysis","confirm","replication-analysis","probe-analysis","stress-analysis")
def package(out):
    start=perf_counter()
    out.mkdir(parents=True,exist_ok=False)
    paths=[]
    costs={}
    usage={}
    for name in RUNS:
        d=LOGS/("n4c-"+name)
        paths.extend(sorted(d.glob("*.json")))
        paths.extend(sorted(d.glob("*.json.gz")))
        if (d/"run.json").exists():
            costs[name]=read(d/"run.json")["seconds"]
        elif (d/"native.json").exists():
            costs[name]=read(d/"native.json")["seconds"]
        total=Counter()
        for p in sorted(d.glob("*.gz")):
            r=read(p)
            for w in r["worlds"]:
                total["worlds"]+=1
                for y in w.get("ys",w.get("outcomes",{}).values()):
                    total["episodes"]+=1
                    total["completed"]+=y.get("utility") is not None
                    total["decisions"]+=len(y.get("trace",[]))
                    total["transitions"]+=y.get("counts",{}).get("transitions",0)+sum(e.get("transitions",0) for e in y.get("events",[]))
            total["transitions"]+=(r.get("graph") or {}).get("transitions",0)
        usage[name]=dict(total)
    results={k:read(LOGS/f"n4c-{k}.json") for k in FILES}
    for name,result in results.items():
        if "seconds" in result:
            costs[name]=result["seconds"]
    write(out/"results.json.gz",results)
    delta=read(LOGS/"n4c-mix.json")
    write(out/"mixed-ridge.json",delta)
    rows,_=load_rows([LOGS/("n4c-"+k) for k in CORE])
    transfer={r["family"]:r for r in rows if r["domain"]=="transfer"}
    for label in ("transfer_repair","transfer_multi_extended"):
        for r in rows:
            if r["domain"]==label:
                if transfer[r["family"]]["worlds"]:
                    raise ValueError("overlapping successful transfer variants")
                transfer[r["family"]]=r
    final=[r for r in rows if r["domain"] in ("natural","target")]+list(transfer.values())
    effective=defaultdict(list)
    for r in transfer.values():
        effective[r["encounter"]].append(r)
    per_encounter={k:one(v) for k,v in effective.items()}
    summary={}
    for group in ("natural","target","transfer"):
        rs=list(transfer.values()) if group=="transfer" else [r for r in final if r["domain"]==group]
        examples=[]
        for r in rs:
            for w in r["worlds"]:
                y,b=w["outcomes"]["plan_gate"],w["outcomes"]["g2"]
                if y["status"]!=b["status"]:
                    examples.append(dict(id=r["id"],encounter=r["encounter"],w=w["world"]["seed"],reference_hp=b["terminal"]["hp"],
                        expert_hp=y["terminal"]["hp"],events=y["events"]))
        summary[group]=examples
    # Timing duplicates development worlds and is never counted as independent evidence.
    timing={}
    counts=defaultdict(Counter)
    baseline=LOGS/"n4c-dev2"
    for p in sorted((LOGS/"n4c-timing").glob("*.gz")):
        r=read(p)
        ref=read(baseline/p.name)["worlds"][0]["outcomes"]
        for name,y in r["worlds"][0]["outcomes"].items():
            if y["trace"]!=ref[name]["trace"] or y["utility"]!=ref[name]["utility"]:
                raise ValueError("instrumentation changed deployed policy")
            counts[name].update(y["counts"])
            counts[name].update(episodes=1,seconds=y["seconds"],actions=len(y["trace"]))
    for name,c in counts.items():
        timing[name]=dict(c)
    report=read(LOGS/"n4c-confirm.json")
    pre={j[3] for j in cohort.plan() if j[2]=="confirm"}|{j["family"] for j in design.jobs() if j["split"]=="confirm"}
    families={r["family"] for r in final}
    native=[entry for name in ("native","native-loss","nativemulti") for entry in read(LOGS/f"n4c-{name}/native.json")["rows"]]
    if not all(entry["result"].get("terminal_match") for entry in native):
        raise ValueError("targeted native mismatch")
    public_checks=Counter()
    path_checks=0
    replica=[read(p) for p in sorted((LOGS/"n4c-replicate").glob("*.gz"))]
    for r in final+replica:
        ws=r["worlds"]
        if r["stop"]!="complete" or not ws:
            raise ValueError("incomplete primary or replication cohort")
        for arm in ("plan_once","q_all","q_budget","g2","plan_once128","pair_once128"):
            if arm not in ws[0]["outcomes"]:
                continue
            signatures=[]
            for w in ws:
                y=w["outcomes"][arm]
                v=y["events"][0] if y["events"] else {}
                signatures.append([w["public"],y["trace"][0],
                    [v.get(k) for k in ("pos","h","a","direct","chosen","paths","scores","path","transitions","stop")]])
            if any(key!=signatures[0] for key in signatures[1:]):
                raise ValueError("same public history gives different root policy")
            public_checks[arm]+=len(ws)-1
        for w in ws:
            for arm,y in w["outcomes"].items():
                if arm.endswith("_budget") and (len(y["events"])>4 or sum(e["transitions"] for e in y["events"])>96):
                    raise ValueError("episode budget exceeded")
                offset=0 if r["domain"]=="natural" else 2
                for e in y["events"]:
                    if e.get("chosen",-1)<0:
                        continue
                    path=e["paths"][e["chosen"]]["steps"]
                    i=e["pos"]-offset
                    if e["h"]!=path[0][0] or y["trace"][i:i+len(path)]!=[a for _,a in path]:
                        raise ValueError("recorded witness was not executed")
                    path_checks+=1
    for j in jobs(True):
        if j["split"]!="dev" and j["family"] in set(sum(delta["families"],[])):
            raise ValueError("training/evaluation leakage")
    with ZipFile(out/"raw.zip","x",compression=ZIP_DEFLATED,compresslevel=5) as archive:
        for p in sorted(set(paths)):
            archive.write(p,p.relative_to(LOGS))
    model=LOGS/"n4b-finalfit/counter_pair-17-20.pt"
    write(out/"details.json.gz",dict(per_encounter=per_encounter,win_switches=summary,native=native,timing=timing,
        paired_public_root_checks=dict(public_checks),executed_plan_checks=path_checks))
    outcomes=[y for r in final for w in r["worlds"] for y in w["outcomes"].values()]
    costs["pack_analysis"]=perf_counter()-start
    info=dict(version="n4c-selective-v1",base="fab07d0e47d206270a2e28b20a31e552c752db11",
        model_hashes={str(p.relative_to(LOGS)):cohort.checksum(p) for p in (cohort.PARENT,model,LOGS/"n4b-plan.json")},
        host=read(design.BUILD/"build.json")["artifacts"],compute_seconds=costs,measured_seconds_sum=sum(costs.values()),
        usage=usage,independent_primary_families=len(families),previous_N4_or_N4B_confirmation_families=len(families&pre),
        primary_root_worlds=sum(len(r["worlds"]) for r in final),primary_episodes=len(outcomes),primary_status=dict(Counter(y["status"] for y in outcomes)),
        primary_transitions=sum(sum(a["transitions"] for a in report["groups"][k]["arms"].values()) for k in ("natural","target","transfer_all_recipes")),
        archive={p.name:dict(sha256=cohort.checksum(p),bytes=p.stat().st_size) for p in sorted(out.iterdir())},
        source={p.name:cohort.checksum(p) for p in sorted(Path(__file__).parent.glob("*.py"))})
    with (out/"manifest.json").open("x",encoding="utf8") as stream:
        json.dump(info,stream,indent=2,allow_nan=False)
if __name__=="__main__":
    package(Path(sys.argv[1]))
