"""Audit every admitted cached decision without decoding its feature tensors."""
from collections import Counter
import numpy as np
from fit import HISTORY
from dc_common import read, write_json
from value import Path, CENTERS, targets, torch

out={}
for root in HISTORY:
    stats=Counter()
    for split, group in read(root/"manifest.json")["shards"].items():
        for item in group:
            with np.load(root/item["name"],allow_pickle=False) as data:
                hp, end, old=data["group"][:,3],data["final_hp"],data["cls"]
                loss=hp-end
                death=old==0
                assert np.array_equal(death,end==0)
                new=targets(torch.from_numpy(hp.copy()),torch.from_numpy(end),torch.from_numpy(death)).numpy()
                wins=~death
                exact=np.asarray(CENTERS)[new[wins]-1]==loss[wins]
                stats[f"{split}_rows"]+=len(new)
                stats["death"]+=int(death.sum())
                stats["negative_wins"]+=int((wins&(loss<0)).sum())
                stats["exact_wins"]+=int(exact.sum())
                near=np.abs(loss[wins])<=20
                assert exact[near].all()
                stats["near_exact_wins"]+=int(near.sum())
    out[root.name]=stats
write_json(Path("logs/m1-dc2b-label-audit.json"),out)
