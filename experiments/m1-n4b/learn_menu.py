"""Crossed distribution/pair-loss and counter treatments on the full public single-action menu."""
from itertools import combinations
from pathlib import Path
import sys
from time import perf_counter
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from teacher import records
from design import LOGS,PARENT,cohort,digest,load,read,write
from arena import tensors
from mechanics import CARD_FEATURES,CARD_WIDTH,PLAYER_FEATURES,PLAYER_WIDTH,PilotEncoder,extend
from value import CENTERS,expected,targets

ARMS={"blind_ce":(False,False),"counter_ce":(True,False),"blind_pair":(False,True),"counter_pair":(True,True)}
EPOCHS=(0,2,6,12,20)


class Encoder(PilotEncoder):
    def __init__(self,vocab,counter):
        super().__init__(vocab,True,True)
        self.counter=counter

    def encode(self,h,history):
        row=super().encode(h,history)
        n=h["nunchaku"] if self.counter else None
        extras=np.array([(n or 0)/9,float(n==9)],dtype=np.float32)
        # Pilot's second card-rule column is the rule-derived Attack flag for this entity.
        attack=row["instances"][:,CARD_FEATURES+1:CARD_FEATURES+2]
        row["instances"]=np.concatenate([row["instances"],attack*extras],axis=1)
        row["player"]=np.concatenate([row["player"],extras])
        return row


def network(seed):
    torch.manual_seed(seed)
    net,meta=load(PARENT)
    extend(net)
    for seq,offset in [(net.encoder.card,24+CARD_FEATURES+CARD_WIDTH),(net.encoder.player,PLAYER_FEATURES+PLAYER_WIDTH)]:
        old=seq[0]
        new=nn.Linear(old.in_features+2,old.out_features)
        with torch.no_grad():
            new.weight.zero_()
            new.weight[:,:offset].copy_(old.weight[:,:offset])
            new.weight[:,offset+2:].copy_(old.weight[:,offset:])
            new.bias.copy_(old.bias)
        seq[0]=new
    slot=len(meta["policies"])
    with torch.no_grad():
        net.policy.weight[slot].copy_(net.policy.weight[meta["policies"].index(meta["deployment"])])
    return net,meta,slot


def restore(path):
    saved=torch.load(path,map_location="cpu",weights_only=True)
    if saved["parent"]!=cohort.checksum(PARENT):
        raise ValueError("Wrong parent")
    net,meta,slot=network(saved["seed"])
    net.load_state_dict(saved["model"])
    return net.eval(),Encoder(meta["vocabulary"],saved["counter"]),slot


def outcomes(r):
    fname=f"{r['id']:03}-{r['counter']}.json.gz"
    files=list(LOGS.glob("n4b-finalmenu-*/"+fname))
    if len(files)!=1:
        raise ValueError("Missing full menu "+fname)
    supplement=read(files[0])
    if (supplement["id"],supplement["counter"])!=(r["id"],r["counter"]):
        raise ValueError("Wrong menu supplement")
    extra=supplement["extra"]
    ret={}
    for b,ws in r["worlds"].items():
        rows=[]
        for w in ws:
            old=w["results"]["0"]["outcomes"]
            row=[]
            for a in r["h"]["actions"]:
                i=a["index"]
                key=digest([[digest(r["h"]),i]])
                y=old[key] if key in old else extra[w["seed"]][str(i)]
                if y["utility"] is None:
                    return None
                if not y["trace"] or y["trace"][0]!=i:
                    raise ValueError("Single-action target mismatch")
                row.append(y)
            rows.append(row)
        ret[b]=rows
    return ret


def examples(rs,counter,meta,slot):
    enc=Encoder(meta["vocabulary"],counter)
    xs=[]
    for r,blocks in rs:
        h=r["h"]
        hist=enc.initial_history()
        for o,i in r["history"]:
            hist=enc.update(hist,o,o["actions"][i])
        ys=blocks["reference"] if r["split"]!="train" else blocks["selection"]+blocks["reference"]
        u=torch.tensor([[y["utility"] for y in w] for w in ys])
        finals=torch.tensor([[y["terminal"]["hp"] for y in w] for w in ys])
        dead=torch.tensor([[y["status"]=="death" for y in w] for w in ys])
        classes=targets(torch.full_like(finals,h["hp"]),finals,dead)
        dist=F.one_hot(classes,1+len(CENTERS)).float().mean(0)
        diff=u[:,:,None]-u[:,None,:]
        se=diff.std(0)/len(u)**.5
        idx=torch.triu_indices(dist.shape[0],dist.shape[0],offset=1)
        ii,jj=idx
        xs.append(dict(id=r["id"],n=r["counter"],row=enc.encode(h,hist)|dict(policy=slot),
            u=u.mean(0),ys=u,dist=dist,greedy=r["paths"]["g2"][0][1],pair=(ii,jj),
            weight=1/(1+(se[ii,jj]/15).square()),initial=r["history"][0][0]["hp"],
            current=h["hp"],maximum=r["history"][0][0]["max_hp"]))
    return xs


def forward(net,batch):
    v,q=net(tensors([x["row"] for x in batch],"cpu"))
    hp=[torch.tensor([x[k] for x in batch])[:,None] for k in ("initial","current","maximum")]
    return v,q,expected(q.softmax(-1),*hp)


@torch.no_grad()
def evaluate(net,rows):
    groups=[]
    for i in range(0,len(rows),24):
        batch=rows[i:i+24]
        _,q,score=forward(net,batch)
        for s,logits,x in zip(score,q,batch):
            u=x["u"]
            s=s[:len(u)]
            a=int(s.argmax())
            ii,jj=x["pair"]
            delta=u[ii]-u[jj]
            correct=(s[ii]-s[jj])*delta>0
            groups.append(dict(id=x["id"],counter=x["n"],pred=s.tolist(),means=u.tolist(),chosen=a,
                g2=x["greedy"],gain=float(u[a]-u[x["greedy"]]),gap_mae=float((s[ii]-s[jj]-delta).abs().mean()),
                correct=int(correct.sum()),nonzero=int((delta!=0).sum()),
                nll=float(-(logits[:len(u)].log_softmax(-1)*x["dist"]).sum(-1).mean())))
    families={i for i in (g["id"] for g in groups)}
    avg=lambda k:float(np.mean([np.mean([g[k] for g in groups if g["id"]==i]) for i in families]))
    return dict(gain=avg("gain"),mae=avg("gap_mae"),nll=avg("nll"),
        acc=sum(g["correct"] for g in groups)/max(1,sum(g["nonzero"] for g in groups)),groups=groups)


def fit(out,arm,seed,ds):
    counter,pair=ARMS[arm]
    net,meta,slot=network(seed)
    sets=[examples(rows,counter,meta,slot) for rows in ds]
    train,dev=sets
    ids=sorted(set(x["id"] for x in train))
    rng=np.random.default_rng(seed)
    optimizer=torch.optim.AdamW(net.parameters(),lr=1.2e-4)
    curve={}
    for epoch in range(21):
        if epoch in EPOCHS:
            d=evaluate(net.eval(),dev)
            d.pop("groups")
            curve[epoch]=d
            torch.save(dict(model=net.state_dict(),counter=counter,parent=cohort.PARENT_SHA,seed=seed),
                       out/f"{arm}-{seed}-{epoch}.pt")
        if epoch==20:
            break
        net.train()
        rng.shuffle(ids)
        for start in range(0,len(ids),8):
            families=ids[start:start+8]
            batch=[x for f in families for x in train if x["id"]==f]
            v,q,score=forward(net,batch)
            losses=[]
            for k,x in enumerate(batch):
                d=x["dist"]
                ce=-(q[k,:len(d)].log_softmax(-1)*d).sum(-1).mean()
                value=-(v[k].log_softmax(-1)*d[x["greedy"]]).sum()
                objective=.5*(ce+value)
                if pair:
                    ii,jj=x["pair"]
                    err=(score[k,ii]-score[k,jj]-(x["u"][ii]-x["u"][jj]))/30
                    weight=x["weight"]
                    objective=objective+(F.smooth_l1_loss(err,torch.zeros_like(err),reduction="none")*weight).sum()/weight.sum()
                losses.append(objective/sum(y["id"]==x["id"] for y in batch))
            optimizer.zero_grad(set_to_none=True)
            (torch.stack(losses).sum()/len(families)).backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True)
            optimizer.step()
    return curve


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1)
    t=perf_counter()
    rows=records()
    def dataset(split):
        return [(r,ys) for r in rows if r["split"]==split and r["stop"]=="complete" and (ys:=outcomes(r)) is not None]
    train,dev=dataset("train"),dataset("dev")
    curves={}
    for seed in (17,29):
        for arm in ARMS:
            curves[f"{arm}-{seed}"]=fit(out,arm,seed,(train,dev))
    # Common epoch, chosen using family-balanced dev difference error across all eight arms.
    epoch=min(EPOCHS[1:],key=lambda k:np.mean([v[k]["mae"] for v in curves.values()]))
    write(out/"selection.json",dict(epoch=epoch,curves=curves))
    confirm=dataset("confirm")
    results={}
    for name in curves:
        net,enc,slot=restore(out/f"{name}-{epoch}.pt")
        _,meta=load(PARENT)
        results[name]=evaluate(net,examples(confirm,enc.counter,meta,slot))
    write(out/"result.json",dict(epoch=epoch,seconds=perf_counter()-t,sizes=[len(s) for s in (train,dev,confirm)],results=results))


if __name__=="__main__":
    run(Path(sys.argv[1]))
