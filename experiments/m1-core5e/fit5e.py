"""Matched MC and MC/TD updates. The full-policy loss estimates the conditional mean."""
import copy,json,math,random
from time import perf_counter
from statistics import mean
import torch
from panel5e import E,OUT,FIVE
from fit5d import logits,differences
from data5e import Corpus,deltas
from semantic import Value
from torch.nn import functional as F

def base_net():
    net=Value()
    net.load_state_dict(torch.load(FIVE/"evidence/v2.pt",weights_only=True))
    return net.eval()

@torch.no_grad()
def evaluate(net,data):
    predictions=[]
    for i in range(0,len(data.pairs),12):predictions+=differences(net,data,data.pairs[i:i+12]).tolist()
    truth=[x[3] for x in data.pairs]
    mse=mean((p-y)**2 for p,y in zip(predictions,truth))
    ce=0
    for i in range(0,len(data.natural),64):
        size=min(64,len(data.natural)-i)
        logp=logits(net,data,data.keys[i:i+size]).log_softmax(-1)
        ce-=float((data.mc[i:i+size]*logp).sum())
    rank=[a*b>0 for a,b in zip(predictions,truth) if b!=0]
    return dict(mse=mse,rmse=math.sqrt(mse),nll=ce/len(data.natural),rank=mean(rank),predictions=predictions)

def fit_arm(name,base,train,dev,out):
    start=perf_counter()
    net=copy.deepcopy(base)
    # Deterministic values inside each complete policy. Both arms see the same inputs in the same order.
    net.eval()
    opt=torch.optim.AdamW(net.parameters(),lr=2.5e-5,weight_decay=.01)
    gen=torch.Generator().manual_seed(5719)
    targets=train.mc if name=="mc" else .35*train.mc+.65*train.td
    with torch.no_grad():
        priors=torch.cat([logits(base,train,train.keys[j:j+64]).softmax(-1) for j in range(0,len(train.keys),64)])
    curve=[]
    for epoch in range(1,9):
        blocks=torch.randperm(len(train.natural),generator=gen).split(64)
        paired=torch.randperm(len(train.pairs),generator=gen).tensor_split(len(blocks))
        for ids,indices in zip(blocks,paired):
            aux=torch.randint(len(train.extra),(max(1,len(ids)//4),),generator=gen)+len(train.natural)
            ids=torch.cat([ids,aux])
            p=logits(net,train,[train.keys[k] for k in ids]).log_softmax(-1)
            label=.75*targets[ids]+.25*priors[ids]
            loss=-(label*p).sum(1).mean()
            if len(indices):
                batch=[train.pairs[i] for i in indices]
                predicted=differences(net,train,batch)
                actual=predicted.new_tensor([x[3] for x in batch])
                # Equal total coefficient for each root over an epoch including exact zero observations.
                loss=loss+.55*((predicted-actual)/45).square().sum()*(len(blocks)/len(train.pairs))
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),2.);opt.step()
        row=evaluate(net,dev);row["epoch"]=epoch;curve.append(row)
        torch.save(net.state_dict(),out/f"{name}-{epoch}.pt")
    best=min(curve,key=lambda r:(r["mse"],r["nll"],r["epoch"]))
    return dict(winner=best["epoch"],curve=curve,seconds=perf_counter()-start)

def run():
    import shutil
    start=perf_counter();torch.set_num_threads(2);torch.manual_seed(5705)
    out=OUT/"fit";out.mkdir(parents=True,exist_ok=True)
    base=base_net()
    train=Corpus("train",base);dev=Corpus("dev",base)
    result=dict(train=train.counts,dev=dev.counts,epoch0=evaluate(base,dev),
                overflow=dict(mean=mean(train.overflow),maximum=max(train.overflow)))
    for name in ("mc","td"):
        result[name]=fit_arm(name,base,train,dev,out)
        shutil.copyfile(out/f"{name}-{result[name]['winner']}.pt",E/(name+".pt"))
    result["seconds"]=perf_counter()-start
    (E/"fit.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":run()
