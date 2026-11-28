"""Behavior cloning versus masked search distillation on the identical natural families."""
import sys
import time
import numpy as np
from common6 import *
from policy6 import MenuPolicy
import torch.nn.functional as F

class Data:
    def __init__(self,part):
        with np.load(WORK/(part+".npz")) as f:
            self.x=torch.from_numpy(f["x"]); self.cards=torch.from_numpy(f["cards"])
            self.v=torch.from_numpy(f["values"]); meta=f["meta"]
        self.size,self.y,self.group,self.family,self.ref=meta[:,:5].astype(int).T
        self.gap=meta[:,5]
        self.start=np.cumsum(self.size)-self.size

    def batch(self,ii):
        span=np.arange(self.size[ii].max())
        valid=span<self.size[ii,None]
        offsets=self.start[ii,None]+np.where(valid,span,0)
        return self.x[offsets],self.cards[offsets],torch.from_numpy(valid),self.v[offsets],torch.tensor(self.y[ii])

@torch.no_grad()
def evaluate(net,data):
    groups=read(E/"source.json")["groups"]
    buckets={}
    cost=[]
    for off in range(0,len(data.y),256):
        ii=np.arange(off,min(off+256,len(data.y)))
        x,c,m,v,y=data.batch(ii); out=net(x,c,m)
        rank=(out.argsort(dim=1,descending=True,stable=True)==y[:,None]).int().argmax(1)+1
        nll=F.cross_entropy(out,y,reduction="none")
        for k in ["all",*groups]:
            use=np.ones(len(ii),bool) if k=="all" else data.group[ii]==groups.index(k)
            if not use.any():continue
            a=buckets.setdefault(k,np.zeros(4))
            a+=np.array([use.sum(),(rank[use]==1).sum(),(rank[use]<=2).sum(),nll[use].sum()])
        for j in np.flatnonzero(np.isin(data.group[ii],[1,2])):
            winner=int(out[j].argmax()); vals=v[j]
            if torch.isfinite(vals[winner]):
                cost.append(float(vals[y[j]]-vals[winner]))
    return {k:dict(n=int(n),top1=a/n,top2=b/n,nll=c/n) for k,(n,a,b,c) in buckets.items()} | dict(comparable_top1=len(cost),estimated_loss=np.mean(cost))

def run(seed):
    tick=time.perf_counter(); torch.set_num_threads(1)
    train,dev=Data("train"),Data("dev")
    for method in ("behavior","distill"):
        torch.manual_seed(seed)
        rng=np.random.default_rng(seed)
        net=MenuPolicy(train.x.shape[1]); opt=torch.optim.AdamW(net.parameters(),lr=.0015)
        best=-1; curve=[]
        weights=np.array([0,3,1.1,.30,1.35,.75,.30,1.4,1,.5])
        for step in range(1,3601):
            ii=rng.integers(len(train.y),size=128)
            x,c,m,v,y=train.batch(ii)
            out=net(x,c,m)
            ce=F.cross_entropy(out,y,reduction="none")
            if method=="behavior":loss=ce.mean()
            else:
                w=torch.tensor(weights[train.group[ii]],dtype=torch.float32)
                loss=(ce*w).sum()/w.sum()
                known=torch.isfinite(v)&m
                keep=known.sum(1)>=2
                if keep.any():
                    t=v[keep].masked_fill(~known[keep],-1e9)
                    teacher=(t/2.5).softmax(-1)
                    s=out[keep].masked_fill(~known[keep],-1e9)
                    loss-=.6*(teacher*s.log_softmax(-1)).sum(1).mean()
            opt.param_groups[0]["lr"]=.0015*(.15+.85*(1+np.cos(np.pi*(step-1)/3600))/2)
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),3);opt.step()
            if step in (600,1800,3600):
                metrics=evaluate(net,dev)
                score=.5*metrics["search_first"]["top1"]+.25*metrics["search_first"]["top2"]+.25*metrics["all"]["top1"]
                curve.append(dict(step=step,score=score,dev=metrics))
                if score>best:
                    best=score; chosen=step
                    torch.save(dict(width=train.x.shape[1],state=net.state_dict()),E/f"{method}-{seed}.pt")
        save(E/f"{method}-{seed}.json",dict(seed=seed,curve=curve,best_step=chosen,score=best,sha256=sha(E/f"{method}-{seed}.pt"),parameters=sum(p.numel() for p in net.parameters())))
    save(E/f"fit-{seed}.json",dict(seconds=time.perf_counter()-tick))
if __name__=="__main__":run(int(sys.argv[1]))
