"""Development cohort calibration and paired uncertainty with a family as the resampling unit."""
import pickle,time
import numpy as np
from settings import *
from campaign5g import representatives

@torch.no_grad()
def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    with (WORK/"corpus.pkl").open("rb") as f:_,d,_=pickle.load(f)
    old=set(read(G.parent/"m1-core5f/evidence/split.json")["dev"])
    fam=np.array(d.family)
    groups={"historical":np.isin(fam,list(old)),"new":~np.isin(fam,list(old)),"all":np.full(len(fam),True)}
    res={}
    for a in ["v2",*representatives()]:
        net=base_net()
        if a!="v2":net.load_state_dict(torch.load(OUT/(a+".pt"),weights_only=True))
        lp=torch.cat([logits(net,d,d.keys[i:i+64]).log_softmax(-1) for i in range(0,len(fam),64)])
        ce=-(d.mc*lp).sum(1).numpy()
        if a=="v2":prior=ce.copy()
        p=lp.exp()[:,0].numpy()
        dead=d.dead.numpy()
        results={}
        for k,mask in groups.items():
            ids=np.unique(fam[mask])
            sums=np.array([(ce-prior)[fam==i].sum() for i in ids])
            count=np.array([(fam==i).sum() for i in ids])
            ix=np.random.default_rng(5707).integers(len(ids),size=(10000,len(ids)))
            ci=np.quantile(sums[ix].sum(1)/count[ix].sum(1),[.025,.975])
            bins=[]
            for b in range(10):
                use=mask&(np.minimum((p*10).astype(int),9)==b)
                if use.any():bins.append([int(use.sum()),float(p[use].mean()),float(dead[use].mean())])
            results[k]=dict(C=int(mask.sum()),families=len(ids),observed_death=float(dead[mask].mean()),predicted_death=float(p[mask].mean()),bins=bins,
                            death_nll=float(ce[mask&dead].mean()),win_nll=float(ce[mask&~dead].mean()),
                            nll_change=float((ce-prior)[mask].mean()),paired_ci=ci.tolist())
        res[a]=results
    save(OUT/"calibration.json",dict(arms=res,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
