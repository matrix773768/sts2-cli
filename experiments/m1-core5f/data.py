"""Assemble actual C transitions and projected whole-policy expectations."""
from collections import Counter
from statistics import mean
from common import *
from fit5d import Sample, logits
from targets5e import terminal_target, temporal_target

class Data(Sample):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.family = []
        self.original = []
        self.pair_ids = []

    def battle(self,r):
        t,s,f = r["trajectory"],r["spec"],r["family"]
        end,cs = t["terminal"],t["states"]
        dead = t["status"]=="Defeat"
        assert dead == (end["hp"]<=0) and end["max_hp"]>0
        for i,c in enumerate(cs):
            assert c["setup"]["stage"]=="before_initial_draw" and c["schema"]=="sts2.core.c.v3"
            assert 0<c["hp"]<=c["max_hp"]
            for z in ("hand","exhaust","discard"):
                assert [v["type"] for v in c["card_state"][z]]==[v["id"]+"#"+str(v["upgrade"]) for v in c[z]]
            key = (f,i)
            self.add(key,c)
            successor = None
            if i+1<len(cs):
                assert cs[i+1]["turn"]==c["turn"]+1
                successor=(f,i+1)
            else:
                assert c["turn"]==end["turn"]
            self.family.append(f)
            self.rows.append((key,successor,c["hp"],end["hp"],dead,s["hp"],s["max_hp"]))

    def condition(self,r):
        t,s=r["trajectory"],r["spec"]
        hp,mx=s["hp"],s["max_hp"]
        assert t["suffix_arm"]=="tactical" and t["suffix_limit"]==32
        projected={}
        for public,c in t["states"].items():
            assert public==digest([c,list(c["belief"]["counts"])])
            self.add(public,c)
            g,x=self.states[public][0]
            projected[public]=hashlib.sha256(g.tobytes()+x.tobytes()).hexdigest()
        laws=[]
        for plan in t["plans"]:
            lookup=dict(projected)
            for k in plan["law"]:
                if "/" in k:
                    status,end=k.split("/")
                    assert status in ("Victory","Defeat")
                    for c in [*t["prefix"]["states"],*t["states"].values(),
                              *(o["trajectory"]["terminal"] for o in t["natural_pair"])]:
                        lookup[digest([status,int(end),c["max_hp"],c["gold"]])]=k
            mass=Counter()
            law=[]
            for pk,p in plan["public_law"].items():
                k=lookup[pk]
                mass[k]+=p
                if pk in projected:law.append(("C",pk,None,p))
                else:
                    status,end=k.split("/")
                    law.append((status,None,utility(hp,int(end),mx,status=="Defeat"),p))
            assert mass.keys()==plan["law"].keys() and all(abs(mass[k]-v)<1e-8 for k,v in plan["law"].items())
            laws.append(law)
        def delta(pair):
            for side in pair:
                end=side["trajectory"]["terminal"]
                assert side["utility"]==utility(hp,end["hp"],mx,side["trajectory"]["status"]=="Defeat")
            return pair[0]["utility"]-pair[1]["utility"]
        ys=[delta(w["outcomes"]) for w in t["worlds"]]
        assert len(ys)==4
        self.pair_ids.append(r["family"])
        self.original.append(dict(family=r["family"],original=delta(t["natural_pair"]),resampled=ys))
        self.pairs.append((laws,hp,mx,mean(ys)))

    @torch.no_grad()
    def prepare(self,base):
        self.keys,successors,hp,end,dead,opening,mx=zip(*self.rows)
        self.hp,self.end,self.dead,self.opening,self.mx=map(torch.tensor,(hp,end,dead,opening,mx))
        self.u=torch.where(self.dead,-50.,payoff(self.opening-self.end,self.mx))
        self.mc=terminal_target(self.hp,self.end,self.dead)
        self.prior=torch.cat([logits(base,self,self.keys[j:j+64]).softmax(-1) for j in range(0,len(hp),64)])
        self.td=self.mc.clone()
        ids=[i for i,k in enumerate(successors) if k is not None]
        assert all(successors[i]==self.keys[i+1] for i in ids)
        after=[i+1 for i in ids]
        self.td[ids],tail=temporal_target(self.prior[after],self.hp[ids],self.hp[after])
        self.counts.update(C=len(hp),adjacent=len(ids),terminal_edges=len(hp)-len(ids),overflow_mean=float(tail.mean()))

def assemble(base):
    split=read(E/"split.json")
    train,dev=Data(),Data()
    held=set(split["dev"])
    editions={}
    for edition in ("data","capacity"):
        d=H5/edition
        m=read(d/"manifest.json")
        p=read(d/"plan.json")
        shards=[s for s in m["shards"] if (s["split"],s["kind"])==("train","natural")]
        policies={s["policy_id"] for s in shards}
        behaviors={s["behavior_id"] for s in shards}
        assert len(policies)==len(behaviors)==1
        editions[edition]=dict(plan=p["id"],manifest=m["id"],policy=policies.pop(),behavior=behaviors.pop(),runtime=p["runtime"])
        for r in scan(d,split="train",kind="natural"):
            (dev if r["family"] in held else train).battle(r)
    assert all(editions["data"][k]==editions["capacity"][k] for k in ("policy","behavior","runtime"))
    for r in scan(H5/"data",split="train",kind="conditional"):
        (dev if r["family"] in held else train).condition(r)
    for data in (train,dev):data.prepare(base)
    save(E/"corpus.json",dict(editions=editions,train=train.counts,dev=dev.counts,
                              conditional=dict(train=train.original,dev=dev.original)))
    return train,dev
