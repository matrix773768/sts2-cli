"""Bundle the actual suffixes, verify ancestry, and quantify finite-world decision error."""
import gzip,zipfile,time
from statistics import mean,stdev
from collections import Counter
import numpy as np
from paths5h import *
import hashlib

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def cluster(v,rng):
    x=np.asarray(v,dtype=float)
    if not len(x):return None
    draws=x[rng.integers(len(x),size=(10000,len(x)))].mean(1)
    return dict(n=len(x),mean=float(x.mean()),ci=np.quantile(draws,[.025,.975]).tolist())
def main():
    tick=time.perf_counter()
    rng=np.random.default_rng(5808)
    rows=[]
    records=[]
    reasons=Counter()
    schema={}
    for shard in range(4):
        dest=E/f"paired-raw-{shard}.zip"
        with zipfile.ZipFile(dest,"w",compression=zipfile.ZIP_STORED) as z:
            for p in sorted(E.glob("root-*.gz")):
                r=json.load(gzip.open(p))
                if r["slot"]//40!=shard:continue
                records.append(r)
                main=[]
                previous=set()
                for j,b in enumerate(r["blocks"]):
                    path=W/f"root-{r['slot']}-{j}.gz"
                    assert sha(path)==b["hash"]
                    z.write(path,path.name)
                    raw=json.load(gzip.open(path))
                    if j==0:parent=raw
                    if raw["eligible"]:
                        assert raw["plans"]==parent["plans"] and raw["graph_id"]==parent["graph_id"] and len(raw["worlds"])==4
                    seeds={w["seed"] for w in raw["worlds"]}
                    assert not previous&seeds
                    previous.update(seeds)
                    if not raw["eligible"]:
                        reasons[b["reason"] or b["status"]]+=1
                    for w in raw["worlds"]:
                        for side in w["outcomes"]:
                            if side.get("utility") is None:continue
                            t=side["trajectory"]
                            assert side["utility"]==(-50 if t["status"]=="Defeat" else 100-r["spec"]["hp"]+t["terminal"]["hp"])
                    if j<2:main.extend(b["deltas"])
                if not r["eligible"]:continue
                x=np.array(main)
                assert len(x)==8
                lo,hi=np.quantile(x[rng.integers(8,size=(10000,8))].mean(1),[.025,.975])
                rows.append(dict(slot=r["slot"],family=r["family"],role=r["role"],split=r["split"],disagree=r["disagree"],
                                 original=r["original"][0]-r["original"][1],ys=main,effect=float(x.mean()),interval=[lo,hi],
                                 sign="positive" if lo>0 else "negative" if hi<0 else "uncertain",
                                 repeat=r["blocks"][2]["deltas"] if len(r["blocks"])>2 else []))
        schema[dest.name]=sha(dest)
    assert len(records)==len({r["family"] for r in records})
    grouped={}
    for split in ("all","train","dev"):
        for role in ("disagreement","representative"):
            group=[r for r in rows if (split=="all" or r["split"]==split) and r["role"]==role]
            ys=[r["effect"] for r in group]
            if not ys:continue
            grouped[split+"-"+role]=dict(effect=cluster(ys,rng),size=mean(map(abs,ys)),positive=sum(v>0 for v in ys),negative=sum(v<0 for v in ys),
                direction=Counter(r["sign"] for r in group),side0_regret=mean(max(0,-v) for v in ys),v2_regret=mean(max(0,v) for v in ys))
    repeats={}
    for subset in ("all","fixed","adaptive-only"):
        gs=[r for r in rows if len(r["repeat"])==4 and (subset=="all" or (r["slot"]%5==2)==(subset=="fixed"))]
        if not gs:continue
        a=np.array([mean(r["ys"][:4]) for r in gs])
        b=np.array([mean(r["ys"][4:]) for r in gs])
        c=np.array([mean(r["repeat"]) for r in gs])
        x=(a+b)/2
        repeats[subset]=dict(n=len(gs),four_rmse=float(np.sqrt(np.mean(((a-c)**2+(b-c)**2)/2))),
                             eight_rmse=float(np.sqrt(np.mean((x-c)**2))),same=int(sum(x*c>0)),opposite=int(sum(x*c<0)),zero=int(sum(x*c==0)))
    examples=[]
    for sign in (1,-1):
        eligible=[r for r in rows if r["split"]=="dev" and r["disagree"] and len(r["repeat"])==4
                  and sign*r["effect"]>0 and sign*mean(r["repeat"])>0]
        if not eligible:continue
        root=max(eligible,key=lambda r:sign*r["effect"])
        record=next(r for r in records if r["slot"]==root["slot"])
        raw=json.load(gzip.open(W/f"root-{root['slot']}-0.gz"))
        facts=raw["natural_pair"][0]["steps"][0]["observation"]["facts"]
        choices=[]
        for plan in record["plans"]:
            action=next(a for a in facts["actions"] if a["index"]==plan["first"])
            card=facts["hand"][action["card"]]["id"] if action["kind"]=="PlayCard" else action["kind"]
            choices.append(dict(card=card,target=action["target"],style=plan["style"]))
        scored=[next(p for p in record["menu"] if [p["first"],p["style"]]==k) for k in record["ids"]]
        examples.append(dict(slot=root["slot"],turn=record["turn"],encounter=record["spec"]["encounter"],hp=facts["hp"],choices=choices,
                             v2_gap=scored[0]["v2"]-scored[1]["v2"],long_gap=scored[0]["long"]-scored[1]["long"],
                             effect=root["effect"],repeat=mean(root["repeat"]),ys=root["ys"]))
    scans=[read(E/f"scans-{i}.json") for i in range(4)]
    coverage=Counter()
    for s in scans:
        for r in s["rows"]:coverage.update(r["coverage"])
    save(E/"production.json",dict(protocol_sha256=sha(H/"protocol.md"),archives=schema,scanned=sum(len(s["rows"]) for s in scans),
        selected=len(records),eligible=len(rows),coverage=coverage,block_failures=reasons,groups=grouped,reassessment=repeats,examples=examples,roots=rows,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
