"""Public-menu root selection adapter for the frozen INFRA-2A checkpoint worker."""
import gzip,hashlib,random,sys,time
from collections import Counter
from statistics import mean
from paths5h import *
sys.path.insert(0,str(INFRA/"experiments/m1-infra2a"))
import worlds as w
import hot_produce as hot
from models import Evaluator,Value
from experience import sha

class Found(Exception):pass

portfolio=hot.portfolio
plan_pair=w.plan_pair
def track(client,*args):
    groups=portfolio(client,*args)
    if getattr(client,"scanning",False):client.options=groups
    return groups

class Probe(w.Recorder):
    scanning=False
    def reference(self,index,limit,m,h,hist,opening):
        ref=super().reference(index,limit,m,h,hist,opening)
        if not self.scanning:return ref
        count=self.count
        count["queries"]+=1
        rv=m.backup([ref],opening)[0]["value"]
        if rv is None:
            count["reference_open"]+=1
            return ref
        count["reference_closed"]+=1
        law=self.state["facts"]["belief"]
        if law["top"] or law["bottom"] or len(law["counts"])<2:return ref
        gs=[g|dict(style=q["style"]) for g,q in self.options if q["value"] is not None]+[ref|dict(style="reference")]
        vs=[q["value"] for _,q in self.options if q["value"] is not None]+[rv]
        if len(gs)<2:return ref
        ls=[self.long.backup([g],opening)[0]["value"] for g in gs]
        def pick(v):
            best=max(range(len(v)-1),key=v.__getitem__)
            return best if v[best]>v[-1] else len(v)-1
        a,b=pick(ls),pick(vs)
        sig=lambda g:w.digest([g["index"],g["policy"]])
        options=[i for i,g in enumerate(gs) if sig(g)!=sig(gs[b]) and w.return_law(g)!=w.return_law(gs[b])]
        if not options:return ref
        count["comparable"]+=1
        disagree=a in options
        if disagree:count["disagreements"]+=1
        if self.role=="representative":
            if h["turn"]<self.target:return ref
            if not disagree:a=random.Random(self.family).choice(options)
        elif not disagree:return ref
        self.root=dict(prefix=dict(steps=self.steps.copy(),root=w.public(self.state)),turn=h["turn"],history=hist.copy(),
                       menu=[dict(first=g["index"],style=g["style"],program=sig(g),v2=v,long=l) for g,v,l in zip(gs,vs,ls)],
                       ids=[(gs[i]["index"],gs[i]["style"]) for i in (a,b)],diff=disagree,opening=opening)
        raise Found

def production(host,m,job,slot):
    root=host.root
    ids=root["ids"]
    def selected_graphs(host,rank):
        groups=portfolio(host,m,rank,root["opening"],"tactical",32)
        h=w.public_b(host.state["facts"])
        ref=host.reference(rank[0],32,m,h,root["history"],root["opening"])
        gs=[g|dict(style=q["style"]) for g,q in groups]+[ref|dict(style="reference")]
        return [next(g for g in gs if (g["index"],g["style"])==tuple(key)) for key in ids]
    def ordered(gs,m,opening,case,role):
        ps=plan_pair(gs,m,opening,case,role)
        return [next(p for p in ps if (p["first"],p["style"])==tuple(k)) for k in ids]
    w.search,w.plan_pair=selected_graphs,ordered
    r=job|dict(prefix=root["prefix"],turn=root["turn"],slot=slot,role=host.role)
    info=dict(family=job["family"],slot=slot,role=host.role,split="dev" if (slot//5+slot%5)%4==0 else "train",
              spec=job["spec"],turn=root["turn"],prefix_hash=w.digest(root["prefix"]),menu=root["menu"],ids=ids,disagree=root["diff"],
              suffix_behavior=w.BEHAVIOR,eligible=False,blocks=[])
    parent=None
    for block in range(3):
        if block==2:
            ys=[y for row in info["blocks"] for y in row["deltas"]]
            if not info["eligible"] or (slot%5!=2 and max(ys)-min(ys)<40):break
        w.seed_for=lambda s,phase,j:((block*160+s)*4+j)*65536+int(w.digest(["5h-pair",block,s,j])[:4],16)
        c=w.produce(host,m,r,"main" if block==0 else "repeat",parent)
        raw=W/f"root-{slot}-{block}.gz"
        with gzip.open(raw,"wt",encoding="utf8",compresslevel=2) as f:json.dump(c,f,separators=(",",":"))
        row=dict(block=block,status=c["status"],reason=c.get("reason"),hash=sha(raw),seeds=[world["seed"] for world in c["worlds"]],deltas=[],
                 sides=[[dict(status=o["status"],reason=o.get("reason"),utility=o.get("utility"),public_key=o.get("public_key")) for o in world["outcomes"]] for world in c["worlds"]])
        info["blocks"].append(row)
        if not c["eligible"]:break
        row["deltas"]=[a["utility"]-b["utility"] for a,b in (world["outcomes"] for world in c["worlds"])]
        if block==0:
            parent=c
            info.update(plans=c["plans"],states=c["states"],original=[o["utility"] for o in c["natural_pair"]])
        if block==1:info["eligible"]=True
    return info

def run(shard):
    tick=time.perf_counter()
    hot.portfolio=track
    jobs=json.load(gzip.open(E/"open.gz"))
    m=w.Models()
    assert m.identity("tactical",32)["id"]==w.POLICY and sha(LONG)==read(LONG.with_suffix(".json"))["sha256"]
    challenger=w.Models()
    net=Value()
    net.load_state_dict(w.torch.load(LONG,weights_only=True))
    challenger.evaluate=Evaluator(net.eval())
    host=Probe(w.Client(W/f"collect-{shard}"))
    host.long=challenger
    scans=[]
    filled=0
    try:
        for i in range(shard,len(jobs),4):
            slot=40*shard+filled
            if filled>=40:break
            job=jobs[i]
            host.family=job["family"]
            host.role="representative" if slot%5==0 else "disagreement"
            host.target=1+int(host.family[:4],16)%4
            host.count=Counter()
            note=dict(index=i,family=host.family,role=host.role)
            host.scanning=True
            try:w.fight(host,job["spec"],m,"tactical",32,w.blank(),require_match=True)
            except Found:
                host.scanning=False
                result=production(host,m,job,slot)
                with gzip.open(E/f"root-{slot:03}.gz","xt",encoding="utf8") as f:json.dump(result,f,separators=(",",":"))
                note["slot"]=slot
                filled+=1
            except w.FAIL as e:note["scan_error"]=str(e)[:350]
            note["coverage"]=dict(host.count)
            scans.append(note)
    finally:host.host.close()
    save(E/f"scans-{shard}.json",dict(rows=scans,seconds=time.perf_counter()-tick))
if __name__=="__main__":run(int(sys.argv[1]))
