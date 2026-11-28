"""Matched-compute scale and supervision experiments, selected exclusively on development."""
import copy
from statistics import mean
from time import perf_counter
from common import *
from data import assemble
from fit5d import logits, differences
from fit5e import base_net

@torch.no_grad()
def metrics(net,d):
    p=torch.cat([logits(net,d,d.keys[i:i+64]).softmax(-1) for i in range(0,len(d.keys),64)])
    pred=differences(net,d,d.pairs)
    actual=torch.tensor([r[3] for r in d.pairs])
    mask=actual!=0
    err=expected(p,d.opening,d.hp,d.mx)-d.u
    bins=[]
    for b in range(10):
        group=(p[:,0]*10).long().clamp(max=9)==b
        if group.any():bins.append([int(group.sum()),float(p[group,0].mean()),float(d.dead[group].float().mean())])
    return dict(nll=float(-(d.mc*p.log()).sum(1).mean()),brier=float((p[:,0]-d.dead.float()).square().mean()),
                calibration=bins,utility_rmse=float(err.square().mean().sqrt()),delta_rmse=float((pred-actual).square().mean().sqrt()),
                rank_correct=int((pred[mask]*actual[mask]>0).sum()),rank_n=int(mask.sum()))

def train_arm(base,d,dev,ids,method,seed):
    tick=perf_counter()
    net=copy.deepcopy(base).eval()
    opt=torch.optim.AdamW(net.parameters(),lr=2.5e-5,weight_decay=.01)
    rng=torch.Generator().manual_seed(seed)
    prng=torch.Generator().manual_seed(seed+1)
    target=d.mc if method=="mc" else .35*d.mc+.65*d.td
    target=.75*target+.25*d.prior
    blocks=[]
    for _ in range(321):
        if len(blocks)>=320:break
        blocks.extend(ids[torch.randperm(len(ids),generator=rng)].split(64))
    curve=[]
    seen=0
    best=None
    for step,ix in enumerate(blocks[:320],1):
        logp=logits(net,d,[d.keys[i] for i in ix]).log_softmax(-1)
        loss=-(target[ix]*logp).sum(1).mean()
        if method=="paired":
            # One uniform root per update, isolated random stream for paired supervision.
            pair=d.pairs[int(torch.randint(len(d.pairs),(1,),generator=prng))]
            loss=loss+.55*((differences(net,d,[pair])-pair[3])/45).square().mean()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(),2.)
        opt.step()
        seen+=len(ix)
        if step in (40,80,160,320):
            row=metrics(net,dev)|dict(step=step,presentations=seen)
            curve.append(row)
            if best is None or row["nll"]<best["nll"]:
                best=row
                weights=copy.deepcopy(net.state_dict())
    return dict(seed=seed,C=len(ids),steps=320,presentations=seen,curve=curve,best=best,seconds=perf_counter()-tick),weights

def main():
    tick=perf_counter()
    torch.set_num_threads(1)
    base=base_net()
    train,dev=assemble(base)
    split=read(E/"split.json")
    baseline=metrics(base,dev)
    result=dict(baseline=baseline,arms={})
    for size,method in [(s,"mc") for s in (128,256,512,945)]+[(945,"td"),(945,"paired")]:
        families=set(split["train"][:size])
        ids=torch.tensor([i for i,f in enumerate(train.family) if f in families])
        name=f"{method}-{size}"
        rows=[]
        best=None
        for seed in (5719,7213,8929):
            row,weights=train_arm(base,train,dev,ids,method,seed)
            rows.append(row)
            if best is None or row["best"]["nll"]<best["best"]["nll"]:
                best=row
                torch.save(weights,E/(name+".pt"))
        result["arms"][name]=dict(runs=rows,seed=best["seed"],step=best["best"]["step"],sha256=sha(E/(name+".pt")))
        save(E/"fit.json",result)
        print(name,flush=True)
    scores={a:min(r["best"]["nll"] for r in v["runs"]) for a,v in result["arms"].items()}
    result["selected"]=min(scores|{"v2":baseline["nll"]},key=(scores|{"v2":baseline["nll"]}).get)
    result["seconds"]=perf_counter()-tick
    save(E/"fit.json",result)
if __name__=="__main__":main()
