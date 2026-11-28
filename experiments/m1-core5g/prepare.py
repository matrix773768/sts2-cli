"""Project released experience once. Reassessment is held out of every optimizer."""
import hashlib,json,pickle,subprocess,time
from collections import Counter
from statistics import mean
from settings import *

def paired_values(r):
    ys=[]
    for w in r["trajectory"]["worlds"]:
        a,b=w["outcomes"]
        for side in (a,b):
            t=side["trajectory"]
            assert side["utility"]==utility(r["spec"]["hp"],t["terminal"]["hp"],r["spec"]["max_hp"],t["status"]=="Defeat")
        ys.append(a["utility"]-b["utility"])
    assert len(ys)==4
    return ys

def append_new(d,r,active):
    case,s=r["trajectory"],r["spec"]
    lookup={}
    for k,c in case["states"].items():
        assert k==digest([c,list(c["belief"]["counts"])])
        d.add(k,c)
        g,x=d.states[k][0]
        lookup[k]=hashlib.sha256(g.tobytes()+x.tobytes()).hexdigest()
    laws=[]
    for p in case["plans"]:
        masses=Counter()
        law=[]
        for pk,prob in p["public_law"].items():
            if pk in p["terminals"]:
                end=p["terminals"][pk]
                kind=end["kind"]
                assert kind in ("Victory","Defeat") and pk==digest([kind,end["hp"],end["max_hp"],end["gold"]])
                label=kind+"/"+str(end["hp"])
                law.append((kind,None,utility(s["hp"],end["hp"],s["max_hp"],kind=="Defeat"),prob))
            else:
                label=lookup[pk]
                law.append(("C",pk,None,prob))
            masses[label]+=prob
        assert p["law"].keys()==masses.keys() and all(abs(masses[k]-v)<1e-8 for k,v in p["law"].items())
        laws.append(law)
    ys=paired_values(r)
    d.pair_ids.append(r["family"])
    d.pairs.append((laws,s["hp"],s["max_hp"],mean(ys)))
    if r["split"]=="train":
        # Equal root sampling, then one observed post-intervention C/terminal label.
        samples=set()
        for w in case["worlds"]:
            for side in w["outcomes"]:
                t=side["trajectory"]
                for c in t["states"]:
                    k=digest([c,list(c["belief"]["counts"])])
                    d.add(k,c)
                    samples.add((k,t["terminal"]["hp"],t["status"]=="Defeat"))
        if samples:active[r["family"]]=sorted(samples)
    return ys

def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    release=read(A/"release.json")
    assert release["id"]==RELEASE==digest({k:v for k,v in release.items() if k!="id"})
    split=read(A/"splits.json")
    old=read(G.parent/"m1-core5f/evidence/split.json")
    order=split["primary_train"]
    assert order[:945]==old["train"] and not set(order)&set(split["extended_train"])
    tr,dev=Data(),Data()
    # Keep the full raw rows on the publisher side. Consume its rank-bearing stream.
    ranks=set()
    with subprocess.Popen([sys.executable,"-B",str(A/"read_primary.py")],cwd=INFRA,stdout=subprocess.PIPE) as proc:
        for line in proc.stdout:
            r=json.loads(line)
            rank=r["primary_rank"]
            assert r["family"]==order[rank-1] and rank not in ranks and r["behavior_id"]==BEHAVIOR and r["policy_id"]==POLICY
            ranks.add(rank)
            tr.battle(r)
        assert proc.wait()==0 and len(ranks)==4096
    # Reorder C rows in frozen family order before batching or building TD edges.
    rankmap={f:i for i,f in enumerate(order)}
    tr.rows.sort(key=lambda row:(rankmap[row[0][0]],row[0][1]))
    tr.family=[row[0][0] for row in tr.rows]
    held=set(old["dev"])
    for base in (H5/"data",H5/"capacity",A/"dev"):
        for r in scan(base,split="dev" if base==A/"dev" else "train",kind="natural"):
            if r["family"] in held or base==A/"dev":
                assert r["policy_id"]==POLICY and r["behavior_id"]==BEHAVIOR
                dev.battle(r)
    for r in scan(H5/"data",split="train",kind="conditional"):
        (dev if r["family"] in held else tr).condition(r)
    active={}
    repeat=[]
    parents={}
    meta=[]
    for part,d in [("train",tr),("dev",dev)]:
        for ed,kind in [("main","conditional"),("repeat","reassessment")]:
            for r in scan(A/ed,split=part,kind=kind):
                t=r["trajectory"]
                assert r["policy_id"]==POLICY and r["suffix_behavior_id"]==BEHAVIOR and r["behavior_id"]==read(A/ed/"plan.json")["protocol_id"]
                signature=(part,r["family"],digest(r["public_prefix"]),digest(t["plans"]),t["graph_id"])
                seeds={w["seed"] for w in t["worlds"]}
                if ed=="main":
                    ys=append_new(d,r,active)
                    parents[r["task_id"]]=(signature,ys,seeds)
                    meta.append(dict(family=r["family"],id=r["task_id"],part=part,ys=ys,original=t["natural_pair"][0]["utility"]-t["natural_pair"][1]["utility"],
                                     natural_admitted=r["family"] in set(order+split["extended_train"]+split["new_dev_eligible"])))
                else:
                    parent,ys,previous=parents[r["original_task_id"]]
                    assert signature==parent and len(seeds)==4 and seeds.isdisjoint(previous)
                    repeat.append(dict(parent=r["original_task_id"],part=part,main=ys,repeat=paired_values(r)))
    base=base_net()
    for d in (tr,dev):d.prepare(base)
    assert (len(tr.keys),len(dev.keys),len(tr.pairs),len(dev.pairs),len(repeat))==(19936,1314,166,51,32)
    with (WORK/"corpus.pkl").open("wb") as f:pickle.dump((tr,dev,active),f,protocol=5)
    save(OUT/"data.json",dict(release=RELEASE,train=tr.counts,dev=dev.counts,active_roots=len(active),active_labels=sum(map(len,active.values())),
                              main=meta,repeats=repeat,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
