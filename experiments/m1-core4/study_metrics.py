"""Aggregate separate seed replications by family and account for every timed job."""
from assessment import rows,ci,utility,load_value
from semantic import *
from statistics import mean,median
from collections import defaultdict
from shutil import copyfile

def readset(files):
    return [row for f in files for row in rows(f)]

def describe(records):
    queries=[q for r in records for q in r.get("queries",[])]
    return dict(n=len(records),families=len({r["family"]for r in records}),status=Counter(r.get("status","error")for r in records),
        C=sum(len(r["states"])for r in records),mid_late_C=sum(c["turn"]>=5 for r in records for c in r["states"]),
        actions=sum(r.get("actions",0)for r in records),queries=len(queries),calls=sum(q["calls"]for q in queries),
        decision_complete=sum(q["coverage"]>=1-1e-9 for q in queries),unique_C=sum(q.get("unique",q.get("unique_C",0))for q in queries),
        settlements=sum(q.get("settles",q.get("settlements",0))for q in queries),
        execution=Counter(q.get("result","G2") for q in queries),used=sum(q["used"]for q in queries))

def paired(arm,base):
    pairs=[(r,base[(r["family"],r["seed"])])for r in arm if r.get("terminal") and base[(r["family"],r["seed"])].get("terminal")]
    group=defaultdict(list);win=defaultdict(list);severe=[];returns=[];common=[];flips=[0,0]
    for r,b in pairs:
        won=r["status"]=="predicted_win";old=b["status"]=="predicted_win"
        severe.append(not won or r["hp"]-r["terminal"]["hp"]>=r["hp"]/2)
        returns.append(utility(r));group[r["family"]].append(utility(r)-utility(b));win[r["family"]].append(int(won)-int(old))
        if won and old:common.append(r["terminal"]["hp"]-b["terminal"]["hp"])
        if won!=old:flips[int(old)]+=1
    return dict(n=len(pairs),wins=sum(r["status"]=="predicted_win" for r,b in pairs),severe=sum(severe),
        joint_win_hp=mean(common) if common else None,win_flips=flips,absolute_utility=mean(returns),
        delta=ci([mean(v) for v in group.values()]),win_delta=ci([mean(v)for v in win.values()]))

def run(out,logs):
    started=perf_counter();torch.set_num_threads(1);arms=("G2","G2search","core3","v0","v1")
    panel=json.load(gzip.open(out/"panels.json.gz"));lookup={j[3]:j[1] for j in panel["confirm"]}
    data={}
    for a in arms:
        data[a]=readset(sorted(out.glob("test-"+a+"-*.gz")))
        for rep in (1,2,3):
            path=logs/f"c4-rep-{rep}-{a}"
            if not (path/"seconds.json").exists():raise ValueError("Incomplete "+str(path))
            dest=out/f"rep-{rep}-{a}.gz"
            if not dest.exists():copyfile(path/"rows.gz",dest)
            data[a].extend(rows(dest))
    key=lambda r:(r["family"],r["seed"])
    b={key(r):r for r in data["G2"]};result={}
    for a,records in data.items():
        assert len(records)==400 and set(map(key,records))==set(b)
        first=records[:100];families={r["family"]for r in records}
        assert len(families)==100
        result[a]=dict(primary=paired(first,b),first_cost=describe(first),four_seeds=paired(records,b),
            by_seed=[paired(records[i:i+100],b)["wins"]for i in range(0,400,100)],
            normal_hp=paired([r for r in records if r["max_hp"]<=100],b))
    v0={key(r):r for r in data["v0"]}
    training={}
    fs=readset((HERE.parent/"m1-core3/evidence").glob("fights*.gz"))
    training["prior_train"]=describe([r for r in fs if r["split"]=="train"]);training["new_G2"]=describe(readset(out.glob("nat*.gz")))
    on=readset(out.glob("on*.gz"))
    for policy in ("v0","paired","error"):training[policy]=describe([r for r in on if r["policy"]==policy])
    training["dev_v0"]=describe(list(rows(out/"val.gz")))
    net=load_value(out/"v1.pt")
    batch=[c for r in data["v0"][:100] for c in r["states"]][:48]
    values=pack([encode(c) for c in batch])
    with torch.inference_mode():
        net(*values);t=perf_counter()
        for _ in range(100):net(*values)
        warm=(perf_counter()-t)/100;t=perf_counter()
        for _ in range(10):net(*pack([encode(c) for c in batch]))
        warm_full=(perf_counter()-t)/10
    g2search={key(r):r for r in data["G2search"]}
    outdata=dict(arms=result,training=training,updated_against_v0=paired(data["v1"],v0),
        updated_against_g2search=paired(data["v1"],g2search),
        panel=dict(families=len(lookup),normal_maxhp=sum(j["max_hp"]<=100 for j in lookup.values()),
            enemies=len({r["encounter"]for r in lookup.values()}),median_deck=median(len(j["deck"]) for j in lookup.values())),
        batch48_forward_seconds=warm,batch48_with_encoding_seconds=warm_full)
    (out/"replication.json").write_text(json.dumps(outdata,indent=2))
    jobs={f.parent.name:json.loads(f.read_text())for f in logs.glob("c4-*/seconds.json")}
    verification=logs/"c4-verify-base/fit.json"
    if verification.exists():jobs["base_reproduction"]=json.loads(verification.read_text())["seconds"]
    for name in ("v0-fit","v1-fit","summary","audit","reference-cost","paired-check"):
        jobs[name]=json.loads((out/(name+".json")).read_text())["seconds"]
    extra=logs/"c4-engineering.json"
    if extra.exists():jobs.update(json.loads(extra.read_text(encoding="utf-8-sig")))
    jobs["metrics"]=perf_counter()-started
    (out/"ledger.json").write_text(json.dumps(dict(jobs_seconds=jobs,summed_seconds=sum(jobs.values()),gpu_seconds=0,
        scope="Sum of timed job wall seconds across lanes. Excludes editing, interpreter startup outside timed regions, import failures, final verification and small untimed engineering checks."),indent=2))

if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
