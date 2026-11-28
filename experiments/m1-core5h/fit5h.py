"""Matched training on the frozen 5G corpus, with an isolated stream of active roots."""
import math,pickle,random,sys,time
from training_data import *
import importlib.util
spec=importlib.util.spec_from_file_location("learn5g",G/"learn.py")
learn=importlib.util.module_from_spec(spec)
spec.loader.exec_module(learn)

@torch.no_grad()
def active_metrics(net,d):
    delta=torch.cat([differences(net,d,d.pairs[i:i+8]) for i in range(0,len(d.pairs),8)])
    y=delta.new_tensor([p[3] for p in d.pairs])
    # On a tie, retain the V2 program (side 2).
    gain=torch.where(delta>0,y,0.)
    regret=y.clamp_min(0)-gain
    return dict(delta=delta.tolist(),gain=float(gain.mean()),regret=float(regret.mean()),rmse=float((delta-y).square().mean().sqrt()),
                switched=int((delta>0).sum()),correct_nonzero=int((delta*y>0).sum()))

def measure(net,dev,active,mask):
    natural=learn.evaluate(net,dev,mask)
    chosen=active_metrics(net,active)
    n=natural["natural"]["all"]
    score=n["nll"]+.006*n["rmse"]+.003*natural["pair_rmse"]+.01*chosen["regret"]
    return dict(natural=n,old_pair_rmse=natural["pair_rmse"],active=chosen,score=score)

def initialize(kind,path):
    net=network(kind).eval()
    keys=net.load_state_dict(torch.load(path,weights_only=True),strict=False)
    assert not keys.unexpected_keys and all(k.startswith("transform.") for k in keys.missing_keys)
    return net

def run(kind,active,seed,tr,dev,old_suffix,new,mask):
    tick=time.perf_counter()
    torch.manual_seed(seed)
    net=initialize(kind,LONG)
    name=f"{kind}-{'active' if active else 'control'}-{seed}"
    opt=torch.optim.AdamW(net.parameters(),lr=8e-5,weight_decay=.01)
    stream=learn.shuffled(torch.arange(len(tr.keys)),torch.Generator().manual_seed(seed),64,True)
    old_rng,aux_rng,new_rng=[random.Random(seed+i) for i in (1,2,3)]
    groups=list(old_suffix.values())
    trace=[]
    best=None
    for step in range(1,2001):
        ix=next(stream)
        lr=8e-5*(.2+.8*(1+math.cos(math.pi*(step-1)/2000))/2)
        opt.param_groups[0]["lr"]=lr
        logp=logits(net,tr,[tr.keys[i] for i in ix]).log_softmax(-1)
        loss=-(logp*tr.mc[ix]).sum(1).mean()
        for data,coefficient,rng in [(tr,.35,old_rng)]+([(new["train"],.55,new_rng)] if active else []):
            pairs=rng.sample(data.pairs,2)
            pred=differences(net,data,pairs)
            label=pred.new_tensor([p[3] for p in pairs])
            loss=loss+coefficient*((pred-label)/45).square().mean()
        ks,end,dead=zip(*(aux_rng.choice(gp) for gp in aux_rng.sample(groups,8)))
        y=terminal_target(torch.tensor([tr.states[k][1] for k in ks]),torch.tensor(end),torch.tensor(dead))
        loss=loss-.15*(logits(net,tr,ks).log_softmax(-1)*y).sum(1).mean()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(),2)
        opt.step()
        if step in (160,600,1200,2000):
            row=measure(net,dev,new["dev"],mask)|dict(step=step)
            trace.append(row)
            if best is None or row["score"]<best["score"]:
                best=row
                torch.save(net.state_dict(),E/(name+".pt"))
    result=dict(name=name,kind=kind,active=active,seed=seed,curve=trace,best=best,sha256=sha(E/(name+".pt")),seconds=time.perf_counter()-tick,
                parameters=sum(p.numel() for p in net.parameters()),steps=2000,natural_presentations=128000)
    save(E/(name+".json"),result)

def main(seed):
    tick=time.perf_counter()
    torch.set_num_threads(1)
    assert sha(W/"corpus.pkl")==read(E/"source.json")["cache_sha256"]
    with (W/"corpus.pkl").open("rb") as f:tr,d,old_suffix=pickle.load(f)
    new,rs=active_data()
    assert len(list(E.glob("scans-*.json")))==4 and not set(new["train"].pair_ids)&set(new["dev"].pair_ids)
    old=set(read(G.parent/"m1-core5f/evidence/split.json")["dev"])
    mask=torch.tensor([f in old for f in d.family])
    if seed==5719:
        save(E/"labels.json",rs)
        historical={}
        for name,net in [("v2",base_net()),("long",initialize("pool",LONG)),("scratch",initialize("pool",SCRATCH))]:
            historical[name]=measure(net,d,new["dev"],mask)
        save(E/"historical.json",historical)
    for kind in ("pool","local","interact"):
        for active in (False,True):run(kind,active,seed,tr,d,old_suffix,new,mask)
    save(E/f"fit-worker-{seed}.json",dict(seconds=time.perf_counter()-tick))
if __name__=="__main__":main(int(sys.argv[1]))
