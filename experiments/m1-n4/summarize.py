"""Aggregate family-paired effects and archive the full experiment, including unsuccessful roots."""
from collections import Counter
import itertools
from pathlib import Path
from statistics import mean, median
from time import perf_counter
import sys

# Load the local experiment before upstream entry points extend sys.path.
from fit import ARMS, data, differences, encode, evaluate
from cohort import BUILD, HERE, PARENT, ROOT, checksum, plan, read, torch, write
from arena import expected, load, tensors
from analyze import measure
from dc_metrics import describe, paired
from learn import restore
from pack import write_zip
from features import Encoder
import numpy as np

LOGS=ROOT/"logs"


def root_effect(left,right):
    keys=("regret","against_g2","q_nll","q_brier")
    groups=list(zip(left["groups"],right["groups"],strict=True))
    assert all(a["id"]==b["id"] for a,b in groups)
    rng=np.random.default_rng(401)
    index=rng.integers(len(groups),size=(4000,len(groups)))
    vals={}
    for key in (*keys,"accuracy"):
        if key=="accuracy":
            # Ratio of correct non-tied pairs, bootstrap whole families.
            den=np.array([sum(p["delta"]!=0 for p in a["pairs"]) for a,b in groups])
            x=np.array([sum(p["delta"]*p["pred"]>0 for p in b["pairs"])-
                        sum(p["delta"]*p["pred"]>0 for p in a["pairs"]) for a,b in groups])
            draws=x[index].sum(1)/den[index].sum(1).clip(1)
            effect=x.sum()/den.sum()
        else:
            x=np.array([b[key]-a[key] for a,b in groups])
            effect=x.mean()
            draws=x[index].mean(1)
        vals[key]=dict(delta=float(effect),ci=np.quantile(draws,[.025,.975]).tolist())
    return vals


def labels(directory,train=False):
    rows=[read(p) for p in sorted(directory.glob("*.json.gz"))]
    qualified=[r for r in rows if r["stop"]=="complete"]
    block="paired" if train else "reference"
    actions=pairs=0
    ds=[]
    active=Counter()
    wcost=Counter()
    states=Counter()
    for r in qualified:
        opts=r["options"]
        actions+=len(opts)
        mat=differences(r,block)
        for i,j in itertools.combinations(range(len(opts)),2):
            d=mat[:,i]-mat[:,j]
            ds.append(dict(id=r["ordinal"],i=opts[i],j=opts[j],delta=float(d.mean()),
                           se=float(d.std(ddof=1)/np.sqrt(len(d))),different=int(np.count_nonzero(d)),
                           pos=int((d>0).sum()),neg=int((d<0).sum())))
            pairs+=1
        states.update(prefix=bool(r["history"]),stacks=bool(r["h"]["mechanism"]["stacks"]),
                      multiple_enemies=len(r["h"]["enemies"])>1)
        for name,ws in r["blocks"].items():
            for w in ws:
                for a,y in w["outcomes"].items():
                    active[name]+=1
                    wcost[name]+=y["seconds"]
                    if name=="paired" and int(a)==opts[0]:
                        wcost["paired_greedy"]+=y["seconds"]
    rejected=Counter()
    for r in rows:
        rejected.update(r.get("reasons",{}))
    return dict(n=len(rows),stops=Counter(r["stop"] for r in rows),actions=actions,pairs=pairs,
        complete=len(qualified),states=states,labels=active,roll_seconds=wcost,rejections=rejected,
        paired_differences=ds,nonzero=sum(d["delta"]!=0 for d in ds),constant=sum(d["se"]==0 for d in ds),
        median_se=median(d["se"] for d in ds),worlds_with_any_difference=sum(d["different"]>0 for d in ds))


def pack(out):
    out.mkdir(parents=True,exist_ok=False)
    t=perf_counter()
    raw=[BUILD/"build.json"]
    archives=[]
    models=[]
    times={}
    report=dict(offline={},offline_effects={},combat={},combat_effects={},labels={},latency_ms={},fixtures={})
    jobs=plan()
    for split in ("train","dev","confirm"):
        d=LOGS/("n4-v2-"+split)
        report["labels"][split]=labels(d,split=="train")
        js=read(d/"manifest.json")["jobs"]
        report["labels"][split].update(deck_range=[min(len(j[1]["deck"]) for j in js),max(len(j[1]["deck"]) for j in js)],
            encounters=Counter(j[1]["encounter"] for j in js),rooms=Counter(j[4] for j in js))
    repeat=[r for d in sorted(LOGS.glob("n4-v2-repeat-*")) for p in sorted(d.glob("*.json.gz"))
            if (r:=read(p))["stop"]=="complete"]
    confirm=data("confirm")
    assert [r["key"] for r in repeat]==[r["key"] for r in confirm]
    torch.set_num_threads(1)
    vecs={}
    for dname in ("diag2","pressure"):
        rows=read(LOGS/f"n4-v2-{dname}/pressure.json.gz")["rows"]
        for r in rows:
            key=dname+str(r["enemy_hp"])
            vecs[key]=dict(h=r["h"],options=r["opts"])
            v=np.array([[y["utility"] for y in w["outcomes"]] for w in r["records"]])
            report["fixtures"][key]=dict(means=v.mean(0).tolist(),se=float((v[:,0]-v[:,1]).std(ddof=1)/np.sqrt(len(v))),
                k=len(v),predictions={})
    for p in [PARENT,*sorted((LOGS/"n4-v2-fit").glob("*.pt"))]:
        name="G2" if p==PARENT else p.stem
        if name=="G2":
            net,meta=load(PARENT)
            enc=Encoder(meta["vocabulary"])
            slot=meta["policies"].index(meta["deployment"])
        else:
            net,enc,slot=restore(p)
            models.append(p)
        report["latency_ms"][name]=measure(net,enc,slot,[r["h"] for r in confirm])
        initial=evaluate(net,enc,slot,confirm)
        high=evaluate(net,enc,slot,repeat)
        report["offline"][name]=dict(k6=initial,k24=high)
        for key,s in vecs.items():
            h=s["h"]
            with torch.inference_mode():
                q=net(tensors([encode(s|dict(history=[]),enc,slot)],"cpu"))[1][0,s["options"]].softmax(-1)
                vals=expected(q,*[torch.tensor(h[k]) for k in ("hp","hp","max_hp")])
            report["fixtures"][key]["predictions"][name]=vals.tolist()
    for seed in ("17","29"):
        for a,b in (("A","B"),("C","D"),("A","C"),("B","D")):
            report["offline_effects"][a+b+seed]={k:root_effect(report["offline"][a+seed][k],report["offline"][b+seed][k])
                for k in ("k6","k24")}
    result={}
    for directory in sorted(LOGS.glob("n4-v2-battle-*")):
        raw.append(directory/"manifest.json")
        for folder in sorted(directory.glob("*-*")):
            files=sorted(folder.glob("*.json.gz"))
            if not files:
                continue
            entries=[read(p) for p in files]
            rows=result[folder.name]=[v["row"] for v in entries]
            assert len(rows)==40 and all(v["ordinal"]==j[0] and v["row"]["family"]==j[3] and
                v["row"]["root"]=={k:r for k,r in j[1].items() if k!="seed"} for v,j in zip(entries,jobs[116:],strict=True))
            counts=Counter()
            for v in entries:
                counts.update(v["counts"])
            report["combat"][folder.name]=describe(rows)|dict(counts=counts)
            times[folder.name]=read(folder/"run.json")["seconds"]
            raw.extend(files+[folder/"run.json"])
    for budget in (0,24):
        for seed in ("17","29"):
            for a,b in (("G2","A"),("A","B"),("C","D"),("A","C"),("B","D"),("G2","D")):
                left=(a if a=="G2" else a+seed)+f"-{budget}"
                right=b+seed+f"-{budget}"
                report["combat_effects"][left+"/"+right]=paired(zip(result[left],result[right],strict=True),bootstrap=True)
    dirs=["train","dev","confirm","fit","repeat-116","repeat-136","diag2","pressure","counter","counter-native",
          "qualify","replay","endcheck"]
    for suffix in dirs:
        d=LOGS/("n4-v2-"+suffix)
        files=sorted([*d.glob("*.json"),*d.glob("*.json.gz")])
        raw.extend(files)
        for p in files:
            if p.name in ("run.json","relic.json.gz","counter_native.json","qualification.json","replay.json","terminal.json"):
                times[d.name]=read(p)["seconds"]
    # Compact summary keeps raw supervision tables, uncertainty and checkpoints individually accessible.
    for p,paths in ((out/"raw.zip",raw),(out/"models.zip",models)):
        write_zip(p,paths)
        archives.append(dict(file=p.name,sha256=checksum(p),bytes=p.stat().st_size))
    report.update(times=times,seconds_sum=sum(times.values()),pack_seconds=perf_counter()-t,archives=archives)
    write(out/"results.json.gz",report)


if __name__=="__main__":
    pack(Path(sys.argv[1]))
