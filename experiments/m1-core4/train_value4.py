"""Fit the continuation-specific distribution and paired utility differences."""
from semantic import *
from collections import Counter
from torch.nn import functional as functional

def rows(path):
    with gzip.open(path,"rt",encoding="utf8") as stream:
        for line in stream:yield json.loads(line)

def run(out,stage,paths):
    out.mkdir(parents=True,exist_ok=False);t=perf_counter();torch.manual_seed(451);torch.set_num_threads(2)
    data={"train":[],"development":[]};ys={k:[] for k in data};counts=Counter();families=set()
    paired=[]; primary={}; alternate=[]
    for p in paths:
        for r in rows(p):
            split=r.get("split","train")
            if split not in data or not r.get("terminal"):continue
            if stage!="base" and r.get("policy")=="paired":
                alternate.append(r);continue
            if stage!="base" and r.get("policy")!="v0":raise ValueError("Continuation mixture")
            if stage!="base":primary[r["family"]]=r
            counts[split]+=1;families.add(r["family"])
            for c in r["states"]:
                data[split].append(encode(c))
                ys[split].append((c["hp"],r["terminal"]["hp"],r["status"]=="death"))
    for alt in alternate:
        main=primary.get(alt["family"])
        if not main:continue
        turn=alt["skip"]+1
        a=next((c for c in main["states"] if c["turn"]==turn),None)
        b=next((c for c in alt["states"] if c["turn"]==turn),None)
        if a is None or b is None or a==b:continue
        def realized(r):
            return -50. if r["status"]=="death" else payoff(torch.tensor(r["hp"]-r["terminal"]["hp"]),torch.tensor(r["max_hp"])).item()
        paired.append((encode(a),encode(b),a["hp"],b["hp"],main["hp"],main["max_hp"],realized(main)-realized(alt)))
    def labels(items):
        hp,end,death=zip(*items);return targets(torch.tensor(hp),torch.tensor(end),torch.tensor(death))
    y,z=labels(ys["train"]),labels(ys["development"]);net=Value()
    if stage!="base":net.load_state_dict(torch.load(stage,weights_only=True))
    opt=torch.optim.AdamW(net.parameters(),lr=.001 if stage=="base" else .00035,weight_decay=.015)
    curve=[];best=1e9
    for ep in range(1,21 if stage=="base" else 13):
        net.train();trainloss=0.
        for idx in torch.randperm(len(y)).split(96):
            pred=net(*pack([data["train"][i] for i in idx.tolist()]));loss=functional.cross_entropy(pred,y[idx])
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(net.parameters(),2);opt.step()
            trainloss+=loss.item()*len(idx)
        if paired:
            for ids in torch.randperm(len(paired)).split(32):
                batch=[paired[i] for i in ids.tolist()]
                a,b,ha,hb,origin,mx,delta=zip(*batch)
                def utility(xs,hp):
                    return expected(net(*pack(xs)).softmax(-1),torch.tensor(origin),torch.tensor(hp),torch.tensor(mx))
                residual=(utility(a,ha)-utility(b,hb))/40.
                pair_loss=.15*functional.smooth_l1_loss(residual,torch.tensor(delta).float()/40.)
                opt.zero_grad();pair_loss.backward();nn.utils.clip_grad_norm_(net.parameters(),2);opt.step()
        net.eval()
        with torch.no_grad():
            val=torch.cat([net(*pack(data["development"][i:i+96])) for i in range(0,len(z),96)])
            nll=functional.cross_entropy(val,z).item()
        curve.append([ep,trainloss/len(y),nll,((val.softmax(-1)[:,0]-(z==0).float())**2).mean().item()])
        if nll<best:
            best=nll;epoch=ep;torch.save(net.state_dict(),out/"model.pt")
    (out/"fit.json").write_text(json.dumps(dict(continuation="G2" if stage=="base" else "v0",epoch=epoch,curve=curve,fights=counts,
        families=len(families),paired_labels=len(paired),states=[len(y),len(z)],parameters=sum(p.numel()for p in net.parameters()),seconds=perf_counter()-t)))
if __name__=="__main__":run(Path(sys.argv[1]),sys.argv[2],sys.argv[3:])
