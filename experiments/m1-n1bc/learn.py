"""Matched G2 adaptation with terminal V and selected-action Q cross entropy."""
import argparse
from collections import Counter
import gzip
import json
import random
from time import perf_counter
from pathlib import Path

from arena import HERE, PARENT, PARENT_SHA, checksum, digest, expected, load, tensors, torch
from mechanics import PilotEncoder, extend
from value import CENTERS, targets
import numpy as np
from torch.nn import functional as F


def restore(path):
    obj = torch.load(path, weights_only=True, map_location="cpu")
    if checksum(PARENT) != obj["parent"] or obj["parent"] != PARENT_SHA:
        raise ValueError("Parent mismatch")
    net, meta = load(PARENT)
    extend(net).load_state_dict(obj["model"])
    return net.eval(), PilotEncoder(meta["vocabulary"], obj["enabled"],obj.get("wide",False)), obj["slot"]


def records(data, encoder, slot, behavior, qualified=False):
    rows = {"train": [], "report": []}
    audit = []
    for p in sorted(data.glob("*.json.gz")):
        with gzip.open(p) as f:
            item = json.load(f)
        r = item["row"]
        if r["behavior"]["model_sha256"] != behavior or r["evidence"] != "prediction_only":
            raise ValueError("Unexpected teacher")
        audit.append(dict(file=p.name, sha256=checksum(p), family=r["family"], status=r["status"],
                          split=r["split"], positions=[]))
        if qualified and r["root"]["encounter"]=="KNOWLEDGE_DEMON_BOSS":
            audit[-1]["excluded"]="unqualified_native_choice_bounds"
            continue
        if not r["complete"]:
            continue
        if r["status"] not in ("predicted_win", "death") or not r["steps"]:
            raise ValueError("Invalid terminal")
        mem = encoder.initial_history()
        length = len(r["steps"])
        rng = random.Random(r["family"])
        n = min(16, length)
        select = {rng.randrange(i*length//n, (i+1)*length//n) for i in range(n)}
        audit[-1]["positions"] = sorted(select)
        for i,s in enumerate(r["steps"]):
            o,a = s["observation"],s["action"]
            if not s["advanced"] or i != s["position"] or o["actions"][a["index"]] != a:
                raise ValueError("Invalid action-to-outcome pairing")
            if i in select:
                rows[r["split"]].append(encoder.encode(o,mem) | dict(chosen=a["index"], policy=slot,
                    hp=o["hp"], final=r["terminal"]["hp"], dead=r["status"]=="death",
                    initial=r["root"]["hp"], maximum=r["root"]["max_hp"]))
            mem = encoder.update(mem,o,a)
    return rows, audit


@torch.inference_mode()
def metrics(net, rows):
    sums = Counter()
    top = []
    for i in range(0,len(rows),32):
        b = tensors(rows[i:i+32], "cpu")
        v,q = net(b)
        pred = q.softmax(-1)
        scores = expected(pred, b["initial"][:,None], b["hp"][:,None], b["maximum"][:,None])
        top.extend(scores.masked_fill(~b["mask"], -torch.inf).argmax(1).tolist())
        cls = targets(b["hp"],b["final"],b["dead"])
        for k,o in (("v",v),("q",q[torch.arange(len(v)),b["chosen"]])):
            p = o.softmax(-1)
            sums[k+"_nll"] += F.cross_entropy(o,cls,reduction="sum").item()
            sums[k+"_brier"] += ((p[:,0]-b["dead"].float())**2).sum().item()
            sums[k+"_pdeath"] += p[:,0].sum().item()
            loss = p[:,1:] @ p.new_tensor(CENTERS) / p[:,1:].sum(1).clamp_min(1e-9)
            sums[k+"_win_mae"] += (loss-b["hp"]+b["final"]).abs()[~b["dead"]].sum().item()
    wins = sum(not r["dead"] for r in rows)
    return dict(n=len(rows),wins=wins,top=top, **{k:v/(wins if "mae" in k else len(rows)) for k,v in sums.items()})


def fit(data, out, seed, enabled, wide=False, qualified=False):
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    if checksum(PARENT) != PARENT_SHA:
        raise ValueError("Unexpected parent")
    net,meta = load(PARENT)
    net = extend(net)
    source = json.loads((data/"run.json").read_bytes())
    behavior = digest(source["definition"])
    slot = len(meta["policies"])
    with torch.no_grad():
        net.policy.weight[slot].copy_(net.policy.weight[meta["policies"].index(meta["deployment"])])
    start=perf_counter()
    rows,audit = records(data,PilotEncoder(meta["vocabulary"],enabled,wide),slot,behavior,qualified)
    (out/"samples.json").write_text(json.dumps(audit))
    prepare=perf_counter()-start
    opt = torch.optim.AdamW(net.parameters(),lr=4e-5)
    order = list(range(len(rows["train"])))
    rng = random.Random(seed)
    start = perf_counter()
    net.train()
    steps = 0
    for epoch in range(3):
        rng.shuffle(order)
        for i in range(0,len(order),32):
            b = tensors([rows["train"][j] for j in order[i:i+32]],"cpu")
            cls = targets(b["hp"],b["final"],b["dead"])
            v,q = net(b,chosen_only=True)
            loss = (F.cross_entropy(v,cls)+F.cross_entropy(q,cls))/2
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True)
            opt.step()
            steps += 1
    seconds = perf_counter()-start
    result = dict(seed=seed,enabled=enabled,wide=wide,qualified=qualified,seconds=seconds,prepare_s=prepare,steps=steps,
                  parameters=sum(p.numel() for p in net.parameters()),training_rows=len(order),
                  report=metrics(net.eval(),rows["report"]))
    torch.save(dict(parent=PARENT_SHA,model=net.state_dict(),enabled=enabled,slot=slot,
                    behavior=behavior,seed=seed,wide=wide,qualified=qualified),out/"model.pt")
    (out/"result.json").write_text(json.dumps(result,indent=2))


if __name__ == "__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("data",type=Path)
    cli.add_argument("output",type=Path)
    cli.add_argument("seed",type=int)
    cli.add_argument("--mechanism",action="store_true")
    cli.add_argument("--wide", action="store_true")
    cli.add_argument("--qualified", action="store_true")
    a=cli.parse_args()
    fit(a.data,a.output,a.seed,a.mechanism,a.wide,a.qualified)
