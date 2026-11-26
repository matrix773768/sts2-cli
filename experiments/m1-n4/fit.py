"""Four matched arms, empirical distribution targets, independent selection and scoring worlds."""
import argparse
import itertools
from statistics import mean
from time import perf_counter

import numpy as np
from cohort import BUILD, PARENT, PARENT_SHA, ROOT, checksum, digest, load, read, torch, write
from arena import expected, tensors
from learn import PilotEncoder, extend
from value import CENTERS, targets

ARMS = {"A": (False,False), "B": (False,True), "C": (True,False), "D": (True,True)}


def data(split):
    directory=ROOT/"logs"/("n4-v2-"+split)
    files=sorted(directory.glob("*.json.gz"))
    jobs=read(directory/"manifest.json")["jobs"]
    run=read(directory/"run.json")
    if run["teacher"]["model"]!=PARENT_SHA or run["teacher"]["budget"]!=0 or run["teacher"]["epsilon"]!=0:
        raise ValueError("Unexpected continuation")
    if run["build"]!=checksum(BUILD/"build.json"):
        raise ValueError("Host identity differs from the collection ledger")
    if [int(p.name.split(".")[0]) for p in files]!=[j[0] for j in jobs]:
        raise ValueError(f"Incomplete {split} ledger")
    items=[read(p) for p in files]
    for r,j in zip(items,jobs,strict=True):
        if (r["ordinal"],r["split"],r["family"])!=(j[0],split,j[3]) or j[2]!=split:
            raise ValueError("Root or family differs from the manifest")
    return [r for r in items if r["stop"]=="complete"]


def encode(r,enc,slot):
    mem=enc.initial_history()
    for h,i in r["history"]:
        mem=enc.update(mem,h,h["actions"][i])
    return enc.encode(r["h"],mem)|dict(policy=slot)


def outcomes(r,block,action):
    return [w["outcomes"][str(action)] for w in r["blocks"][block]]


def distribution(r,ys):
    hp=torch.full((len(ys),),r["h"]["hp"])
    ids=targets(hp,torch.tensor([y["terminal"]["hp"] for y in ys]),torch.tensor([y["status"]=="death" for y in ys]))
    return torch.bincount(ids,minlength=1+len(CENTERS)).float()/len(ys)


def example(r,enc,slot,cf):
    opts=r["options"]
    greedy=outcomes(r,"paired",opts[0])
    q=[distribution(r,outcomes(r,"paired",a)) for a in opts] if cf else [distribution(r,greedy+outcomes(r,"extra",opts[0]))]
    return encode(r,enc,slot),distribution(r,greedy),opts if cf else opts[:1],torch.stack(q)


def differences(r, block):
    return np.array([[w["outcomes"][str(a)]["utility"] for a in r["options"]] for w in r["blocks"][block]])


@torch.inference_mode()
def evaluate(net,enc,slot,rows):
    groups=[]
    for r in rows:
        opts=r["options"]
        b=tensors([encode(r,enc,slot)],"cpu")
        v,q=net(b)
        p=q[0,opts].softmax(-1)
        h=r["h"]
        initial=r["history"][0][0] if r["history"] else h
        scores=expected(p,*[torch.tensor(x) for x in (initial["hp"],h["hp"],initial["max_hp"])]).numpy()
        sel=differences(r,"selection")
        ref=differences(r,"reference")
        mu=ref.mean(0)
        best=int(sel.mean(0).argmax())
        pred=int(scores.argmax())
        pairs=[]
        for i,j in itertools.combinations(range(len(opts)),2):
            delta=ref[:,i]-ref[:,j]
            d=float(delta.mean())
            pairs.append(dict(delta=d,se=float(delta.std(ddof=1)/np.sqrt(len(delta))),pred=float(scores[i]-scores[j]),
                              independent=float((sel[:,i]-sel[:,j]).mean())))
        target=torch.stack([distribution(r,outcomes(r,"reference",a)) for a in opts])
        vtarget=target[0]
        vd=float(vtarget[0])
        death=target[:,0]
        pv=float(v[0].softmax(-1)[0])
        groups.append(dict(id=r["ordinal"],options=opts,pred=pred,best=best,scores=scores.tolist(),means=mu.tolist(),
            pairs=pairs,regret=float(mu[best]-mu[pred]),against_g2=float(mu[pred]-mu[0]),
            q_nll=float(-(target*q[0,opts].log_softmax(-1)).sum(-1).mean()),
            v_nll=float(-(vtarget*v[0].log_softmax(-1)).sum()),
            q_brier=float((p[:,0].square()-2*p[:,0]*death+death).mean()),
            q_pdeath=float(p[:,0].mean()),death=float(death.mean()),v_brier=pv*pv-2*pv*vd+vd))
    pairs=[p for g in groups for p in g["pairs"]]
    nonzero=[p for p in pairs if p["delta"]]
    replicated=[p for p in nonzero if p["independent"]*p["delta"]>0]
    return dict(n=len(groups),pairs=len(pairs),nonzero=len(nonzero),replicated=len(replicated),
        acc=mean(p["pred"]*p["delta"]>0 for p in nonzero) if nonzero else None,
        replicated_acc=mean(p["pred"]*p["delta"]>0 for p in replicated) if replicated else None,
        delta_mae=mean(abs(p["pred"]-p["delta"]) for p in pairs),
        **{k:mean(g[k] for g in groups) for k in ("regret","against_g2","q_nll","v_nll","q_brier","v_brier","q_pdeath","death")},
        groups=groups)


def fit(out,arm,seed,train,dev,confirm):
    enabled,cf=ARMS[arm]
    torch.manual_seed(seed)
    net,meta=load(PARENT)
    extend(net)
    slot=len(meta["policies"])
    with torch.no_grad():
        net.policy.weight[slot].copy_(net.policy.weight[meta["policies"].index(meta["deployment"])])
    enc=PilotEncoder(meta["vocabulary"],enabled,True)
    samples=[example(r,enc,slot,cf) for r in train]
    rng=np.random.default_rng(seed)
    opt=torch.optim.AdamW(net.parameters(),lr=4e-5)
    result=dict(arm=arm,seed=seed,n=len(samples),parameters=sum(x.numel() for x in net.parameters()),curve={})
    elapsed=0.
    for step in range(73):
        if step in (0,12,36,72):
            report=evaluate(net.eval(),enc,slot,dev)
            report.pop("groups")
            result["curve"][step]=report
        if step==72:
            break
        tick=perf_counter()
        net.train()
        batch=[samples[i] for i in rng.integers(len(samples),size=24)]
        v,q=net(tensors([x[0] for x in batch],"cpu"))
        vloss=-(v.log_softmax(-1)*torch.stack([x[1] for x in batch])).sum(-1).mean()
        logq=q.log_softmax(-1)
        qloss=-torch.stack([(logq[i,x[2]]*x[3]).sum(-1).mean() for i,x in enumerate(batch)]).mean()
        opt.zero_grad(set_to_none=True)
        ((vloss+qloss)*.5).backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True)
        opt.step()
        elapsed+=perf_counter()-tick
    result["update_s"]=elapsed
    result["confirm"]=evaluate(net.eval(),enc,slot,confirm)
    path=out/f"{arm}{seed}.pt"
    torch.save(dict(parent=PARENT_SHA,model=net.state_dict(),enabled=enabled,slot=slot,wide=True,seed=seed,
                    behavior="frozen-G2-direct"),path)
    result["sha256"]=checksum(path)
    write(out/f"{arm}{seed}.json",result)


if __name__=="__main__":
    import pathlib
    p=argparse.ArgumentParser()
    p.add_argument("out",type=pathlib.Path)
    p.add_argument("--seeds",nargs="+",type=int,default=[17,29])
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1)
    if checksum(PARENT)!=PARENT_SHA:
        raise ValueError("Frozen G2 changed")
    start=perf_counter()
    splits=[data(s) for s in ("train","dev","confirm")]
    families=[r["family"] for rows in splits for r in rows]
    assert len(families)==len(set(families))
    for seed in args.seeds:
        for arm in ARMS:
            fit(args.out,arm,seed,*splits)
    write(args.out/"run.json",dict(seconds=perf_counter()-start,seeds=args.seeds))
