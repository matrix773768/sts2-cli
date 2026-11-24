"""Resumable Monte Carlo migration from public SV3A/SV4A shards."""
import argparse
import os
from time import perf_counter

import numpy as np
from torch.nn import functional as F

from value import ROOT, Path, checksum, initialize, targets, torch, CENTERS
from dc_common import read, write_json, digest
from loop_learn import Pool, merge, load_cache
from train import atomic_save

HISTORY = [ROOT/"logs/m1-sv3a-data", *(ROOT/"logs/m1-sv4a-formal/features"/s for s in ("D1","D2","S1","S2"))]
PARENT = ROOT/"logs/m1-sv4a-formal/models/D2/best.pt"


def progress(done,target,checkpoint,started):
    path = os.getenv("INF1_PROGRESS")
    if path:
        write_json(Path(path),dict(done=done,target=target,checkpoint=str(checkpoint.resolve()) if checkpoint else None,
                                  throughput=done/max(.001,perf_counter()-started)))


def stopped():
    path=os.getenv("INF1_STOP")
    return path and Path(path).exists()


def migrated(root, split, policies, limit):
    manifest=read(root/"manifest.json")
    key=manifest.get("policy")
    slots=manifest.get("policies")
    if limit:
        manifest["shards"][split]=manifest["shards"][split][:limit]
    arrays=load_cache(root,manifest,split)
    for array in arrays:
        if key:
            array["policy"].fill(policies.index(key))
        else:
            array["policy"]=np.array([policies.index(name) for name in slots],dtype=np.int16)[array["policy"]]
        current, end=array["group"][:,3],array["final_hp"]
        death=array["cls"]==0
        if not np.array_equal(death,end==0):
            raise ValueError("Invalid historical terminal")
        array["cls"]=targets(torch.from_numpy(current.copy()),torch.from_numpy(end),torch.from_numpy(death)).numpy()
    return arrays


def score(net, pools, rng, device, batches=8):
    stats={}
    with torch.inference_mode():
        for _ in range(batches):
            block=merge([pools.take(256,rng)],device)
            result=net(block,chosen_only=True)[1]
            prob=result.softmax(-1)
            cls=block["cls"].long()
            actual=block["group"][:,3]-block["final_hp"]
            centers=prob.new_tensor(CENTERS)
            win=cls!=0
            for hp in (80,160,999):
                mask=block["group"][:,2]==hp
                d=stats.setdefault(hp,dict(n=0,brier=0.,nll=0.,wins=0,mae=0.,tail=0,tail_error=0.,
                                            deaths=0,predicted_deaths=0.,zero=0,predicted_zero=0.,
                                            low_1_5=0,predicted_1_5=0.,low_6_10=0,predicted_6_10=0.))
                d["n"]+=int(mask.sum())
                d["brier"]+=float(((prob[:,0]-(~win).float())**2)[mask].sum())
                d["nll"]+=float(F.cross_entropy(result,cls,reduction="none")[mask].sum())
                d["deaths"]+=int((mask&~win).sum())
                d["predicted_deaths"]+=float(prob[mask,0].sum())
                residual=((prob[:,1:]@centers)/(1-prob[:,0]).clamp_min(1e-7)-actual).abs()
                d["wins"]+=int((mask&win).sum())
                d["mae"]+=float(residual[mask&win].sum())
                tail=mask&win&(actual>=50)
                d["tail"]+=int(tail.sum())
                d["tail_error"]+=float(residual[tail].sum())
                for a,b,name,pred in ((0,0,"zero","predicted_zero"),(1,5,"low_1_5","predicted_1_5"),
                                      (6,10,"low_6_10","predicted_6_10")):
                    d[name]+=int((mask&win&(actual>=a)&(actual<=b)).sum())
                    d[pred]+=float(prob[mask,1:][:,(centers>=a)&(centers<=b)].sum())
    for d in stats.values():
        for key,denom in (("brier","n"),("nll","n"),("mae","wins"),("tail_error","tail")):
            d[key]=d[key]/d[denom] if d[denom] else None
    return stats


def fit(out,device,updates,batch,limit=0,epoch=32,parent=None,extra=()):
    out.mkdir(parents=True,exist_ok=True)
    started=perf_counter()
    torch.set_num_threads(2)
    torch.manual_seed(714031)
    if parent:
        from value import load
        net,meta=load(parent)
        meta.pop("model")
    else:
        net,meta=initialize(PARENT)
    sources=[*HISTORY,*extra]
    for source in sources:
        m=read(source/"manifest.json")
        for key in ([m["policy"]] if "policy" in m else m["policies"]):
            if key not in meta["policies"]:
                meta["policies"].append(key)
    if len(meta["policies"])>net.policy.num_embeddings:
        raise ValueError("Policy registry exhausted")
    if parent and extra:
        meta["deployment"]=read(extra[0]/"manifest.json")["policy"]
    net.to(device)
    optimizer=torch.optim.AdamW(net.parameters(),lr=.00015)
    identity=digest(dict(parent=meta["parent"],sources=[checksum(p/"manifest.json") for p in sources],
                         continuation=checksum(parent) if parent else None,
                         batch=batch,updates=updates,limit=limit,device=device,epoch=epoch))
    path=out/"resume.pt"
    done=0
    if path.exists():
        saved=torch.load(path,map_location="cpu",weights_only=True)
        if saved["identity"]!=identity:
            raise ValueError("Training identity differs")
        net.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        done=saved["done"]
    progress(done,updates,path if path.exists() else None,started)
    if stopped() and done<updates:
        return 75
    pools={split:Pool([arr for p in sources for arr in migrated(p,split,meta["policies"],limit)])
           for split in ("train","validation")}
    recent=Pool([arr for p in extra for arr in migrated(p,"train",meta["policies"],limit)]) if parent and extra else None
    while done<updates:
        net.train()
        for i in range(done,min(done+epoch,updates)):
            rng=np.random.default_rng(714031+i)
            blocks=([pools["train"].take(batch//2,rng),recent.take(batch-batch//2,rng)]
                    if recent and batch>1 else [pools["train"].take(batch,rng)])
            block=merge(blocks,device)
            v,q=net(block,chosen_only=True)
            label=block["cls"].long()
            loss=(F.cross_entropy(v,label)+F.cross_entropy(q,label))/2
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.)
            optimizer.step()
        done=i+1
        net.eval()
        metrics=score(net,pools["validation"],np.random.default_rng(839),device)
        write_json(out/f"update-{done:05}.json",dict(loss=float(loss.detach()),validation=metrics))
        atomic_save(path,meta|dict(model=net.state_dict(),optimizer=optimizer.state_dict(),done=done,identity=identity))
        progress(done,updates,path,started)
        if stopped() and done<updates:
            return 75
    atomic_save(out/"best.pt",meta|dict(model=net.state_dict()))
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--device",choices=("cuda","cpu"),default="cuda")
    parser.add_argument("--updates",type=int,required=True)
    parser.add_argument("--batch",type=int,default=512)
    parser.add_argument("--shards",type=int,default=0)
    parser.add_argument("--epoch",type=int,default=32)
    parser.add_argument("--parent",type=Path)
    parser.add_argument("--extra",type=Path,nargs="*",default=[])
    args=parser.parse_args()
    raise SystemExit(fit(args.output,args.device,args.updates,args.batch,args.shards,args.epoch,args.parent,args.extra))
