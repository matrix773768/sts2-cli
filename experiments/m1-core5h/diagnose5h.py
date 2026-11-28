"""Inspect train/dev regret, unseen repeat labels, and the learned residual pathway."""
import pickle,time
from statistics import mean
from training_data import *
from semantic import pack

@torch.no_grad()
def main():
    tick=time.perf_counter()
    torch.set_num_threads(1)
    streams,labels=active_data()
    with (W/"corpus.pkl").open("rb") as f:_,dev,_=pickle.load(f)
    def score(net,d):
        return torch.cat([differences(net,d,d.pairs[i:i+8]) for i in range(0,len(d.pairs),8)])
    replay={}
    for name,path in [("v2",None),("long",LONG)]:
        parent=base_net()
        if path:parent.load_state_dict(torch.load(path,weights_only=True))
        errors=[]
        for split,d in streams.items():
            predictions=score(parent,d).tolist()
            ls=[r for r in labels if r["split"]==split]
            for value,root in zip(predictions,ls,strict=True):
                r=json.load(gzip.open(E/f"root-{root['slot']:03}.gz"))
                v=[next(p[name] for p in r["menu"] if [p["first"],p["style"]]==k) for k in r["ids"]]
                errors.append(abs(value-(v[0]-v[1])))
        assert max(errors)<.002
        replay[name]=max(errors)
    output={}
    for file in sorted(E.glob("*.pt")):
        meta=read(file.with_suffix(".json"))
        net=network(meta["kind"]).eval()
        net.load_state_dict(torch.load(file,weights_only=True))
        result={}
        for split,d in streams.items():
            pred=score(net,d)
            y=pred.new_tensor([p[3] for p in d.pairs])
            selected=pred>0
            ls=[r for r in labels if r["split"]==split]
            ix=[i for i,r in enumerate(ls) if r["repeat"]]
            truth=pred.new_tensor([mean(ls[i]["repeat"]) for i in ix])
            result[split]=dict(roots=len(y),rmse=float((pred-y).square().mean().sqrt()),regret=float((y.clamp_min(0)-y*selected).mean()),
                               repeat_n=len(ix),repeat_rmse=float((pred[ix]-truth).square().mean().sqrt()),
                               repeat_regret=float((truth.clamp_min(0)-truth*selected[ix]).mean()))
        if meta["kind"]!="pool":
            # Disabling only the residual measures reliance of this fitted checkpoint on that pathway.
            # It does not retrain the rest of the network after removal.
            before=score(net,streams["dev"])
            ratio=[]
            for i in range(0,len(dev.keys),64):
                _,x,m=pack([dev.states[k][0] for k in dev.keys[i:i+64]])
                v=net.entity(x)
                delta=net.transform(v,m)-v
                ratio.extend((delta.square().sum(-1)[m]/v.square().sum(-1)[m].clamp_min(1.e-12)).sqrt().tolist())
            net.transform.forward=lambda v,m:v
            after=score(net,streams["dev"])
            result["ablation"]=dict(mean_relative_token_norm=mean(ratio),changed=int(((before>0)!=(after>0)).sum()),
                                    mean_abs_delta_change=float((before-after).abs().mean()))
        output[file.stem]=result
    save(E/"diagnostics.json",dict(models=output,production_value_max_error=replay,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
