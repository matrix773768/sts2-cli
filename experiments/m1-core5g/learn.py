"""Equal compute curves and validation-stopped checkpoint selection on a fixed grid."""
import copy,json,math,pickle,random,sys,time
from settings import *

@torch.no_grad()
def evaluate(net,d,old):
    logp=torch.cat([logits(net,d,d.keys[i:i+96]).log_softmax(-1) for i in range(0,len(d.keys),96)])
    p=logp.exp()
    pred=expected(p,d.opening,d.hp,d.mx)
    before=expected(d.prior,d.opening,d.hp,d.mx)
    natural={}
    for name,ix in [("all",torch.ones_like(old)),("historical",old),("new",~old)]:
        natural[name]=dict(nll=float(-(logp[ix]*d.mc[ix]).sum(1).mean()),brier=float((p[ix,0]-d.dead[ix].float()).square().mean()),
                           rmse=float((pred[ix]-d.u[ix]).square().mean().sqrt()),change=float((pred[ix]-before[ix]).abs().mean()))
    delta=torch.cat([differences(net,d,d.pairs[i:i+12]) for i in range(0,len(d.pairs),12)])
    y=delta.new_tensor([r[3] for r in d.pairs])
    return dict(natural=natural,pair_rmse=float((delta-y).square().mean().sqrt()),correct=int((delta*y>0).sum()),nonzero=int((y!=0).sum()),delta=delta.tolist())

def score(m):
    a=m["natural"]["all"]
    return a["nll"]+.006*a["rmse"]+.004*m["pair_rmse"]

def shuffled(ids,rng,bs,full):
    pending=torch.empty(0,dtype=torch.long)
    while True:
        order=ids[torch.randperm(len(ids),generator=rng)]
        if full:order=torch.cat([pending,order])
        for batch in order.split(bs):
            if full and len(batch)<bs:pending=batch
            else:
                pending=torch.empty(0,dtype=torch.long)
                yield batch

def run(name,seed,tr,d,active,old,order):
    t=time.perf_counter()
    method,n=name.rsplit("-",1)
    size=int(n)
    families=order[:size] if method!="redraw" else sorted(order,key=lambda f:digest(["5g-redraw",f]))[:size]
    familyset=set(families)
    ids=torch.tensor([i for i,f in enumerate(tr.family) if f in familyset])
    rng=torch.Generator().manual_seed(seed)
    prng=random.Random(seed+1)
    torch.manual_seed(seed)
    net=Value().eval() if method=="scratch" else base_net()
    conservative=method=="conservative"
    batch=64 if conservative else 96
    high_rate=method in ("scratch","matched")
    steps=320 if conservative else (6400 if high_rate else 2400)
    lr=2.5e-5 if conservative else (.001 if high_rate else .0002)
    opt=torch.optim.AdamW(net.parameters(),lr=lr,weight_decay=.01)
    # Mix true tactical32 returns with the fixed, one-step V2 approximation.
    target=.35*tr.mc+.65*tr.td if method in ("td","pair","active") else tr.mc
    if conservative:target=.75*target+.25*tr.prior
    stream=shuffled(ids,rng,batch,not conservative)
    active_groups=list(active.values())
    curve=[]
    best=None
    seen=0
    grid=([40,80,160,320] if conservative else [80,320,800,1600,2400,4000,6400])
    probe=ids[torch.linspace(0,len(ids)-1,512).long()]
    dest=OUT/f"{name}-{seed}.pt"
    for step in range(1,steps+1):
        ix=next(stream)
        seen+=len(ix)
        if not conservative:
            for group in opt.param_groups:group["lr"]=lr*(.15+.85*(1+math.cos(math.pi*(step-1)/steps))/2)
        p=logits(net,tr,[tr.keys[i] for i in ix]).log_softmax(-1)
        loss=-(p*target[ix]).sum(1).mean()
        if method in ("pair","active"):
            pairs=prng.sample(tr.pairs,2)
            est=differences(net,tr,pairs)
            loss=loss+.55*((est-est.new_tensor([r[3] for r in pairs]))/45).square().mean()
        if method=="active":
            # Keep pair and natural batches matched across methods.
            if step==1:aux_rng=random.Random(seed+2)
            rows=[aux_rng.choice(group) for group in aux_rng.sample(active_groups,16)]
            ks,end,dead=zip(*rows)
            y=terminal_target(torch.tensor([tr.states[k][1] for k in ks]),torch.tensor(end),torch.tensor(dead))
            loss=loss-.25*(logits(net,tr,ks).log_softmax(-1)*y).sum(1).mean()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(),2)
        opt.step()
        if step in grid:
            m=evaluate(net,d,old)
            with torch.no_grad():
                lp=torch.cat([logits(net,tr,[tr.keys[i] for i in chunk]).log_softmax(-1) for chunk in probe.split(64)])
                train_nll=float(-(lp*tr.mc[probe]).sum(1).mean())
            row=m|dict(step=step,presentations=seen,passes=seen/len(ids),train_probe_nll=train_nll,score=score(m))
            curve.append(row)
            if best is None or row["score"]<best["score"]:
                best=row
                torch.save(net.state_dict(),dest)
    return dict(name=name,seed=seed,C=len(ids),represented_families=len(set(tr.family[i] for i in ids)),batch=batch,steps=steps,curve=curve,best_step=best["step"],
                score=best["score"],sha256=sha(dest),seconds=time.perf_counter()-t)

def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    with (WORK/"corpus.pkl").open("rb") as f:tr,dev,active=pickle.load(f)
    old=set(read(G.parent/"m1-core5f/evidence/split.json")["dev"])
    mask=torch.tensor([f in old for f in dev.family])
    order=read(A/"splits.json")["primary_train"]
    worker=int(sys.argv[1])
    if worker==0 and len(sys.argv)==2:save(OUT/"baseline.json",evaluate(base_net(),dev,mask))
    jobs=[(f"{method}-{n}",seed) for n in (945,2048,4096) for method in ("conservative","tuned")
          for seed in (5719,7213)]
    jobs += [(name,seed) for name in ("scratch-4096","td-4096","pair-4096","active-4096","redraw-945") for seed in (5719,7213)]
    supplementary=sys.argv[2:]==["--initialization"]
    if supplementary:
        jobs=[(name,seed) for name in ("matched-4096","scratch-945","scratch-2048") for seed in (5719,7213)]
    for name,seed in jobs[worker::2]:
        path=OUT/f"{name}-{seed}.json"
        if path.exists():continue
        res=run(name,seed,tr,dev,active,mask,order)
        save(path,res)
        print(name,seed,round(res["seconds"],1),flush=True)
    label="init-worker" if supplementary else "worker"
    save(OUT/f"{label}-{worker}.json",dict(seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
