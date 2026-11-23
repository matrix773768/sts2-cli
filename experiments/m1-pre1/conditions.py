"""Measure order reversals and multihit generalization on held-out deck families."""
import argparse
from collections import Counter
import json
from pathlib import Path

import torch

from train import load_policy,load_shard,minibatches


@torch.inference_mode()
def score(root, checkpoint, device, batch_size):
    net,vocabulary = load_policy(checkpoint,device)
    manifest = json.loads((root/"manifest.json").read_bytes())
    if manifest["identity"]["vocabulary"] != vocabulary:
        raise ValueError("Held-out vocabulary differs")
    inflame = vocabulary.index("INFLAME")+2
    twin = vocabulary.index("TWIN_STRIKE")+2
    counts, hits = Counter(),Counter()
    for shard in manifest["shards"]["evaluation"]:
        arrays = load_shard(root,shard)
        mask = arrays["order_mask"]
        arrays = {name: array[mask] for name,array in arrays.items()}
        for batch in minibatches(arrays,batch_size,device,None):
            _,_,_,logit = net(batch,aux=True)
            n = logit.numel()
            arange = torch.arange(n,device=device)
            refs = batch["refs"][arange[:,None],batch["pair"].long(),0].long()
            card_ids = batch["cards"][arange[:,None],refs]
            first = card_ids[arange,(1-batch["order"]).long()]
            outcome = (logit >= 0) == (batch["order"] == 1)
            masks = dict(buff_first=first==inflame, lethal_first=(first!=inflame),
                         twin_strike=(card_ids==twin).any(1))
            for name,mask in masks.items():
                counts[name] += int(mask.sum().item())
                hits[name] += int((outcome & mask).sum().item())
    return {name:dict(n=n,accuracy=hits[name]/n if n else None) for name,n in counts.items()}


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("features",type=Path)
    p.add_argument("weights",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    a=p.parse_args()
    torch.set_num_threads(2)
    report={arm:score(a.features,a.weights/f"{arm}.pt",a.device,512)
            for arm in ("initial","mechanism","final")}
    a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
