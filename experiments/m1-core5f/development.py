"""Paired comparisons of the frozen representatives on the development families."""
from collections import Counter
from statistics import mean
from time import perf_counter
import numpy as np
from common import *
from data import assemble
from fit5d import logits,differences
from fit5e import base_net

@torch.no_grad()
def main():
    tick=perf_counter()
    torch.set_num_threads(1)
    base=base_net()
    tr,d=assemble(base)
    split=read(E/"split.json")
    fit=read(E/"fit.json")
    sample_count={}
    for size in (128,256,512,945):
        families=set(split["train"][:size])
        ix=[i for i,f in enumerate(tr.family) if f in families]
        sample_count[size]=dict(battles=size,C=len(ix),battles_with_C=len(set(tr.family[i] for i in ix)))
    g=np.array(d.family)
    counts=np.array([(g==f).sum() for f in split["dev"]])
    boot=np.random.default_rng(5001).integers(len(counts),size=(10000,len(counts)))
    original=np.array([x["original"] for x in d.original])
    target=np.array([mean(x["resampled"]) for x in d.original])
    values={}
    base_losses=None
    for a in ["v2",*fit["arms"]]:
        net=base_net()
        if a!="v2":
            path=E/(a+".pt")
            assert sha(path)==fit["arms"][a]["sha256"]
            net.load_state_dict(torch.load(path,weights_only=True))
        p=torch.cat([logits(net,d,d.keys[i:i+64]).log_softmax(-1) for i in range(0,len(g),64)])
        ce=-(d.mc*p).sum(1).numpy()
        if base_losses is None:base_losses=ce.copy()
        deltas=np.array([(ce-base_losses)[g==f].sum() for f in split["dev"]])
        vals=deltas[boot].sum(1)/counts[boot].sum(1)
        pred=differences(net,d,d.pairs).numpy()
        values[a]=dict(nll_delta=float((ce-base_losses).mean()),ci=np.quantile(vals,[.025,.975]).tolist(),
                       orig_rmse=float(np.mean((pred-original)**2)**.5),predictions=pred.tolist())
    # Cross-check full public-law expectation differences against the producer's stored V2 values.
    stored={r["family"]:r["trajectory"]["plans"][0]["value"]-r["trajectory"]["plans"][1]["value"]
            for r in scan(H5/"data",split="train",kind="conditional")}
    errors=[]
    for corpus in (tr,d):
        pred=differences(base,corpus,corpus.pairs).tolist()
        errors.extend(abs(x-stored[f]) for x,f in zip(pred,corpus.pair_ids))
    assert max(errors)<.001
    save(E/"development.json",dict(sizes=sample_count,values=values,v2_plan_max_error=max(errors),
                                   original_vs_four_rmse=float(np.mean((target-original)**2)**.5),
                                   seconds=perf_counter()-tick))
if __name__=="__main__":main()
