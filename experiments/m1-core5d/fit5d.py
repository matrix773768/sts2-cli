"""Fit a continuation-specific categorical value and the expected difference of full policies."""
import json,random
from collections import Counter
from time import perf_counter
from statistics import mean
from panel5d import E,OUT,FIVE,rows
from semantic import Value,encode,pack,expected,targets,torch,nn
from search5 import cached_row
import torch.nn.functional as F

class Sample:
    def __init__(self):
        self.states={}
        self.distributions=[]
        self.pairs=[]
        self.counts=Counter()
    def add(self,key,c):
        if key not in self.states:self.states[key]=(encode(c,row_fn=cached_row),c["hp"])
    def load(self,split):
        for path in sorted(E.glob(split+"-V2-*.gz")):
            for r in rows(path):
                if not r["terminal"]:continue
                assert r["arm"]=="V2"
                self.counts["battles"]+=1
                for i,c in enumerate(r["states"]):
                    key=(r["family"],r["seed"],i)
                    self.add(key,c)
                    self.distributions.append((key,r["terminal"]["hp"],r["status"]=="death"))
                    self.counts["natural_C"]+=1
        for path in sorted(E.glob("pairs-"+split+"-*.gz")):
            for r in rows(path):
                if "outcomes" not in r:continue
                assert r["continuation"]=="5C-V2-high"
                outs=r["outcomes"]
                if not all(o.get("matched") and o.get("utility") is not None for o in outs):continue
                for key,c in r["states"].items():self.add(key,c)
                for o in outs:
                    if o["realized"] is not None:
                        self.distributions.append((o["realized"],o["terminal_hp"],o["status"]=="death"))
                        self.counts["observed_pair_C"]+=1
                laws=[plan["law"] for plan in r["plans"]]
                assert all(abs(sum(p for _,_,_,p in law)-1)<1e-8 for law in laws)
                delta=outs[0]["utility"]-outs[1]["utility"]
                self.pairs.append((laws,r["hp"],r["max_hp"],delta))
                self.counts["nonzero"]+=int(delta!=0)
                self.counts["pairs"]+=1
        return self
def logits(net,data,keys):
    return net(*pack([data.states[k][0] for k in keys]))
def dist_loss(net,base,data,batch):
    keys,ends,deaths=zip(*batch)
    y=targets(torch.tensor([data.states[k][1] for k in keys]),torch.tensor(ends),torch.tensor(deaths))
    pred=logits(net,data,keys)
    with torch.no_grad():prior=logits(base,data,keys).softmax(-1)
    return F.cross_entropy(pred,y),F.kl_div(pred.log_softmax(-1),prior,reduction="batchmean")
def differences(net,data,batch):
    keys=list(dict.fromkeys(k for laws,_,_,_ in batch for law in laws for kind,k,v,p in law if kind=="C"))
    probs={}
    for start in range(0,len(keys),64):
        chunk=keys[start:start+64]
        probs.update(zip(chunk,logits(net,data,chunk).softmax(-1)))
    raw=[];orig=[];current=[];maximum=[];weights=[];idx=[];fixed=[0.]*(len(batch)*2)
    for i,(laws,hp,mx,delta) in enumerate(batch):
        for j,law in enumerate(laws):
            for kind,k,v,p in law:
                pos=i*2+j
                if kind!="C":fixed[pos]+=p*v;continue
                raw.append(probs[k]);orig.append(hp);current.append(data.states[k][1]);maximum.append(mx);weights.append(p);idx.append(pos)
    values=torch.tensor(fixed)
    if raw:
        u=expected(torch.stack(raw),torch.tensor(orig),torch.tensor(current),torch.tensor(maximum))
        values=values.index_add(0,torch.tensor(idx),u*torch.tensor(weights))
    return values[::2]-values[1::2]
@torch.no_grad()
def measure(net,base,data):
    net.eval();nll=0.
    for i in range(0,len(data.distributions),96):
        b=data.distributions[i:i+96];nll+=float(dist_loss(net,base,data,b)[0])*len(b)
    estimates=torch.cat([differences(net,data,data.pairs[i:i+12]) for i in range(0,len(data.pairs),12)])
    true=torch.tensor([r[3] for r in data.pairs]);mask=true!=0
    error=F.smooth_l1_loss(estimates/40,true/40).item()
    rank=float(((estimates[mask]*true[mask])>0).float().mean()) if mask.any() else .5
    nll/=len(data.distributions)
    return dict(nll=nll,pair_huber=error,rank=rank,score=nll+.5*error+.4*(1-rank))
def fit(out=None,report=None):
    start=perf_counter();torch.manual_seed(553);torch.set_num_threads(2)
    train=Sample().load("train").load("train2")
    dev=Sample().load("dev").load("dev2")
    out=out or OUT/"full-fit";out.mkdir(parents=True,exist_ok=True)
    net=Value();base=Value()
    weights=torch.load(FIVE/"evidence/v2.pt",weights_only=True)
    net.load_state_dict(weights);base.load_state_dict(weights);base.eval()
    opt=torch.optim.AdamW(net.parameters(),lr=.00018,weight_decay=.012)
    baseline=measure(base,base,dev);curve=[]
    for ep in range(1,9):
        net.train()
        for ids in torch.randperm(len(train.distributions)).split(64):
            batch=[train.distributions[i] for i in ids.tolist()]
            nll,kl=dist_loss(net,base,train,batch)
            opt.zero_grad();(nll+.45*kl).backward();nn.utils.clip_grad_norm_(net.parameters(),2);opt.step()
        ix=[i for i,r in enumerate(train.pairs) if r[3]!=0 or (i+ep)%3==0]
        random.Random(553+ep).shuffle(ix)
        # Disable dropout for branch comparisons; equal successors must receive equal values.
        net.eval()
        for i in range(0,len(ix),12):
            batch=[train.pairs[j] for j in ix[i:i+12]]
            pred=differences(net,train,batch);true=torch.tensor([z[3] for z in batch])
            mask=true!=0
            loss=F.smooth_l1_loss(pred/40,true/40)
            if mask.any():loss=loss+.18*F.softplus(-pred[mask]*true[mask].sign()/12).mean()
            if loss.requires_grad:
                opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(net.parameters(),2);opt.step()
        score=measure(net,base,dev);curve.append(dict(epoch=ep,**score))
        torch.save(net.state_dict(),out/f"epoch{ep}.pt")
    shortlist=sorted(curve,key=lambda z:z["score"])[:2]
    (report or E/"fit.json").write_text(json.dumps(dict(train=train.counts,development=dev.counts,baseline=baseline,curve=curve,
        shortlist=[r["epoch"] for r in shortlist],seconds=perf_counter()-start,optimizer="AdamW 0.00018, 8 epochs"),indent=2))
if __name__=="__main__":fit()
