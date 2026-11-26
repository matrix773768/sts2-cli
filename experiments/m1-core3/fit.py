"""Checkpoint selection uses only development NLL. Confirmation is evaluated after both arms freeze."""
import copy
from collections import Counter
from experience import *
from value_net import *
import torch.nn.functional as F

def summarize(logits,y):
    p=logits.softmax(-1);death=(y==0).float()
    cal=[]
    for i in range(5):
        m=(p[:,0]>=i/5)&(p[:,0]<(i+1)/5 if i<4 else p[:,0]<=1)
        if m.any():cal.append([int(m.sum()),p[m,0].mean().item(),death[m].mean().item()])
    return dict(n=len(y),nll=F.cross_entropy(logits,y).item(),brier=((p[:,0]-death)**2).mean().item(),calibration=cal)

def run(out,files):
    out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1)
    t=perf_counter()
    fights=[json.loads(l) for f in files for l in gzip.open(f)]
    groups={k:[r for r in fights if r["split"]==k] for k in ("train","development","confirmation")}
    metrics={};models={}
    def tensors(rows,arm):
        pairs=[(s,r) for r in rows if r.get("terminal") for s in r["states"]]
        x=torch.from_numpy(np.stack([features(s,arm) for s,r in pairs]))
        y=targets(torch.tensor([s["hp"] for s,r in pairs]),torch.tensor([r["terminal"]["hp"] for s,r in pairs]),
            torch.tensor([r["status"]=="death" for s,r in pairs]))
        return x,y
    for arm in ("simple","mechanism"):
        torch.manual_seed(317)
        net=network(arm);opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.01)
        x,y=tensors(groups["train"],arm);v,z=tensors(groups["development"],arm)
        best=float("inf");curve=[]
        for epoch in range(1,51):
            for idx in torch.randperm(len(y)).split(64):
                loss=F.cross_entropy(net(x[idx]),y[idx]);opt.zero_grad();loss.backward();opt.step()
            if epoch in (1,2,4,8,16,32,50):
                with torch.no_grad():a=summarize(net(x),y);b=summarize(net(v),z)
                curve.append(dict(epoch=epoch,train=a,development=b))
                if b["nll"]<best:best=b["nll"];models[arm]=copy.deepcopy(net.state_dict());at=epoch
        metrics[arm]=dict(curve=curve,best=best,epoch=at,parameters=sum(p.numel() for p in net.parameters()))
        torch.save(models[arm],out/(arm+".pt"))
    chosen=min(metrics,key=lambda a:metrics[a]["best"])
    for arm in metrics:
        x,y=tensors(groups["confirmation"],arm);net=network(arm);net.load_state_dict(models[arm])
        with torch.no_grad():metrics[arm]["confirmation"]=summarize(net(x),y)
    info={k:dict(families=len({r["family"] for r in rs}),fights=len(rs),states=sum(len(r["states"])for r in rs),
        actions=sum(r.get("actions",0) for r in rs),statuses=dict(Counter(r.get("status","error") for r in rs))) for k,rs in groups.items()}
    (out/"fit.json").write_text(json.dumps(dict(selected=chosen,arms=metrics,split=info,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":run(Path(sys.argv[1]),sys.argv[2:])
