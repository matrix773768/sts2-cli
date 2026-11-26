"""Interleaved, single-threaded CPU costs for projection-to-all-Q on identical decisions."""
from pathlib import Path
import sys
from time import perf_counter
import json
import random

import numpy as np
from analyze import entries
from arena import ROOT, PARENT, load, tensors, torch
from learn import restore
from sv_data import Encoder


@torch.inference_mode()
def bench(output):
    torch.set_num_threads(1)
    net, meta = load(PARENT)
    arms = {"frozen": (net,Encoder(meta["vocabulary"]),meta["policies"].index(meta["deployment"]))}
    arms.update({n:restore(ROOT/f"logs/n1bc-clean-{n}/model.pt") for n in ("base","mech","wide")})
    states = []
    for item in entries(ROOT/"logs/n1bc-cohort"):
        r = item["row"]
        if r["split"] == "report" and r["root"]["encounter"]!="KNOWLEDGE_DEMON_BOSS":
            states.extend(s["observation"] for s in r["steps"][::7])
    lat = {name:[] for name in arms}
    randomizer = random.Random(3301)
    for pass_id in range(3):
        for obs in states:
            order=list(arms)
            randomizer.shuffle(order)
            for name in order:
                net,enc,slot=arms[name]
                hist=enc.initial_history()
                start=perf_counter()
                row=enc.encode(obs,hist) | dict(policy=slot)
                middle=perf_counter()
                net(tensors([row],"cpu"))[1].softmax(-1)
                end=perf_counter()
                if pass_id:
                    lat[name].append([(middle-start)*1000,(end-middle)*1000,(end-start)*1000])
    output.write_text(json.dumps({k:dict(n=len(v), columns=["encode","collate_net_softmax","total"],
                                         median_ms=np.median(v,axis=0).tolist(),
                                         p90_ms=np.quantile(v,.9,axis=0).tolist()) for k,v in lat.items()},indent=2))


if __name__=="__main__":
    bench(Path(sys.argv[1]))
