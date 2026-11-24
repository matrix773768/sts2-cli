"""Trajectory-balanced replay and resumable Monte Carlo continuation per generation."""
import argparse
from collections import Counter
from contextlib import closing, nullcontext
import gzip
import json
from pathlib import Path
import sqlite3
from time import perf_counter

import numpy as np
import torch

from loop_common import HERE, checksum, config, digest, sources, write_json
from sv_data import Encoder, Shards, encode, examples, policy_key
from sv_model import VERSION, contract, load
from sv_train import losses, sample_rows
from train import atomic_save, load_shard


def prepare(ledger, root_path, output, parent, cfg):
    identity = dict(ledger=checksum(ledger/"results.sqlite"), roots=checksum(root_path),
                    parent=checksum(parent), examples=12, source=checksum(Path(__file__)))
    if (output/"manifest.json").exists():
        existing = json.loads((output/"manifest.json").read_bytes())
        if existing["identity"] != identity:
            raise ValueError("Generation feature identity changed")
        return existing
    output.mkdir(parents=True, exist_ok=True)
    from loop_battle import read_ledger
    _, saved = load(parent)
    encoder = Encoder(saved["vocabulary"])
    bins = saved["spec"]["bins"]
    with closing(sqlite3.connect((ledger/"results.sqlite").resolve().as_uri()+"?mode=ro",uri=True)) as db:
        raw = db.execute("SELECT json FROM contract").fetchone()[0]
        production = json.loads(raw)
    roots = json.loads(root_path.read_bytes())
    if (not production["purpose"].startswith("experience_") or production["purpose"] != roots["purpose"]
            or identity["roots"] != production["manifest"] or not production["definition"]["exploration"].endswith(
                f":{cfg['exploration']}")):
        raise ValueError("Invalid production cohort, exploration, or manifest")
    key = f"sts2.sv4a.prediction_only.v1|{digest(production['definition'])}|conditional"
    if key in saved["policies"] or len(saved["policies"]) >= saved["spec"]["policy_slots"]:
        raise ValueError("Policy identity already in parent or policy-slot capacity exhausted")
    writer = Shards(output)
    seen, sizes, status = set(), Counter(), Counter()
    with gzip.open(output/"terminals.jsonl.gz", "wb", compresslevel=3) as stream:
        for item in read_ledger(ledger):
            row, ordinal = item["row"], item["ordinal"]
            _, private, split, family, room = roots["jobs"][ordinal]
            if (policy_key(row["behavior"]) != key or row["family"] != family or row["split"] != split
                    or row["room"] != room or family in seen or
                    row["root"] != {k:v for k,v in private.items() if k != "seed"}):
                raise ValueError("Experience provenance, policy or family mismatch")
            seen.add(family)
            status[row["status"]] += 1
            if not row["complete"]:
                continue
            block = list(examples(row, encoder, dict(hp_bins=bins), len(saved["policies"]), ordinal, 12))
            writer.add(split, block)
            sizes[split] += 1
            sizes[split+"_rows"] += len(block)
            stream.write(encode(dict(ordinal=ordinal, split=split, terminal=row["terminal"], status=row["status"],
                          cumulative_loss=row["cumulative_loss"], length=row["length"])) + b"\n")
    target = production["attempts"] or len(roots["jobs"])
    if len(seen) != target or sizes["train"] < int(.75*target) or sizes["validation"] < 30:
        raise ValueError(f"Production ledger failed formal coverage admission: {dict(sizes)} of {target}")
    for split in writer.paths:
        writer.flush(split)
    report = dict(identity=identity, policy=key, definition=production["definition"], sizes=sizes,
                  statuses=status, shards=writer.paths, vocabulary=saved["vocabulary"], spec=saved["spec"],
                  slot=len(saved["policies"]))
    write_json(output/"manifest.json", report)
    print(roots["purpose"], dict(sizes), dict(status), flush=True)
    return report


def load_cache(root, manifest, split):
    results = []
    for item in manifest["shards"][split]:
        if checksum(root/item["name"]) != item["sha256"]:
            raise ValueError("Damaged replay shard")
        results.append(load_shard(root,item))
    return results


class Pool:
    def __init__(self, shards):
        self.shards = shards
        self.trajectories = []
        for array in shards:
            _, start, length = np.unique(array["trajectory"], return_index=True, return_counts=True)
            self.trajectories.append((start,length))
        weights = np.asarray([len(start) for start, _ in self.trajectories],dtype=np.float64)
        self.probabilities = weights / weights.sum()

    def take(self, count, rng):
        # Choose a shard in proportion to its trajectory count, then sample trajectories uniformly.
        index = rng.choice(len(self.shards), p=self.probabilities)
        start, length = self.trajectories[index]
        choices = rng.choice(len(start), count, replace=count > len(start))
        indices = start[choices] + rng.integers(length[choices])
        return {key: arr[indices] for key, arr in self.shards[index].items()
                if key not in ("weight","trajectory","old_logp")}


def merge(blocks, device):
    data = {}
    for key in blocks[0]:
        items = [block[key] for block in blocks]
        sizes = [item.shape[1:] for item in items]
        if len(set(sizes)) > 1:
            # The PRE1 cache has variable menu/zone lengths on axis 1 only.
            maximum = max(size[0] for size in sizes)
            padded = np.zeros((sum(len(item) for item in items), maximum, *sizes[0][1:]), dtype=items[0].dtype)
            at = 0
            for item in items:
                padded[at:at+len(item),:item.shape[1]] = item
                at += len(item)
            combined = padded
        else:
            combined = np.concatenate(items)
        data[key] = torch.from_numpy(combined).to(device)
    return data


@torch.inference_mode()
def validate(net, shards, device, historic=False):
    net.eval()
    total = torch.zeros((net.policy.num_embeddings, 11), dtype=torch.float64, device=device)
    rng = np.random.default_rng(71394290)
    for arrays in shards:
        if historic:
            indices, weights = sample_rows(arrays, 2, rng)
        else:
            indices, weights = np.arange(len(arrays["cls"])), arrays["weight"]
        for offset in range(0,len(indices),512):
            ix = indices[offset:offset+512]
            batch = merge([{k:v[ix] for k,v in arrays.items() if k not in ("trajectory","old_logp","weight")}],device)
            weight = torch.from_numpy(weights[ix]).to(device)
            target, winner = batch["cls"].long(), batch["cls"].ne(0)
            heads = net(batch, chosen_only=True)
            columns = [weight]
            for result in heads:
                prob = net.probabilities(result)
                nll, _ = losses(net,result,batch)
                dead = (prob[:,0]-target.eq(0).float()).square()
                conditional = prob[:,1:] / (1-prob[:,:1]).clamp_min(1.e-12)
                ratio = batch["final_hp"].float()/batch["final_max"].float()
                crps = (conditional.cumsum(1)[:,:-1] - (net.fractions[:-1] >= ratio[:,None]).float()).square().mean(1)
                absolute = (net.expected_hp(result,batch["group"][:,4])-batch["final_hp"]).abs()
                columns.extend([weight*nll,weight*dead,weight*winner*crps,weight*absolute,weight*winner])
            total.index_add_(0,batch["policy"].long(),torch.stack(columns,dim=1).double())
    sums = total.cpu().numpy()

    def scores(row):
        return {name:dict(nll=float(part[0]/row[0]), brier=float(part[1]/row[0]),
                          crps=float(part[2]/part[4]) if part[4] else None, mae=float(part[3]/row[0]))
                for name,part in zip(("v","q"), (row[1:6],row[6:]), strict=True)}
    return dict(overall=scores(sums.sum(0)), by_slot={str(i):scores(row) for i,row in enumerate(sums) if row[0]>0})


def fit(history, current, previous, parent, parent_optimizer, out, cfg, device, until):
    out.mkdir(parents=True,exist_ok=True)
    input_paths = {"history":history, "current":current}
    if previous:
        input_paths["previous"] = previous
    manifests = {name:json.loads((path/"manifest.json").read_bytes()) for name,path in input_paths.items()}
    nominal = dict(history=256,current=154,previous=102) if previous else dict(history=256,current=256)
    if sum(nominal.values()) != cfg["batch"]:
        raise ValueError("Replay proportions require the frozen 512-decision batch")
    identity = dict(config=cfg, data={name:checksum(path/"manifest.json") for name,path in input_paths.items()},
                    parent=checksum(parent), optimizer=checksum(parent_optimizer), sizes=nominal,
                    implementation=sources("loop_learn.py"), model=contract(), torch=str(torch.__version__), device=device)
    net, saved = load(parent,device)
    snapshot = torch.load(parent_optimizer,map_location="cpu",weights_only=True)
    if (saved["epoch"] != snapshot["epoch"] or not all(torch.equal(value, snapshot["model"][name])
            for name,value in saved["model"].items())):
        raise ValueError("Parent weights and optimizer differ")
    manifest = manifests["current"]
    new_slot = manifest["slot"]
    if new_slot != len(saved["policies"]) or manifest["identity"]["parent"] != checksum(parent):
        raise ValueError("New policy slot is incompatible with parent")
    if previous and manifests["previous"]["policy"] != saved["policies"][manifests["previous"]["slot"]]:
        raise ValueError("Earlier replay slot changed")
    registry = [*saved["policies"],manifest["policy"]]
    optimizer = torch.optim.AdamW(net.parameters(),lr=cfg["lr"],fused=device=="cuda")
    optimizer.load_state_dict(snapshot["optimizer"])
    for group in optimizer.param_groups:
        group["lr"] = cfg["lr"]
        group.pop("initial_lr",None)
        group["fused"] = device=="cuda"
    previous_condition = manifest["definition"]["continuation"]
    prior_slot = saved["policies"].index(previous_condition)
    with torch.no_grad():
        net.policy.weight[new_slot].copy_(net.policy.weight[prior_slot])
        for moment in optimizer.state[net.policy.weight].values():
            if isinstance(moment,torch.Tensor) and moment.shape == net.policy.weight.shape:
                moment[new_slot].zero_()
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,cfg["epochs"],eta_min=cfg["lr"]*.1)
    for name in input_paths:
        if manifests[name]["vocabulary"] != saved["vocabulary"]:
            raise ValueError("Replay vocabulary mismatch")
    train = {name:Pool(load_cache(path,manifests[name],"train")) for name,path in input_paths.items()}
    valid = {name:load_cache(path,manifests[name],"validation") for name,path in input_paths.items()}
    measure = lambda: {name:validate(net,group,device,historic=name=="history") for name,group in valid.items()}
    checkpoint = out/"resume.pt"
    epoch, updates, elapsed, best, curve, presents = 0,0,0.,float("inf"),[],Counter()
    if checkpoint.exists():
        cold = torch.load(checkpoint,map_location="cpu",weights_only=True)
        if cold["identity"] != identity:
            raise ValueError("Generation training resume mismatch")
        net.load_state_dict(cold["model"])
        optimizer.load_state_dict(cold["optimizer"])
        schedule.load_state_dict(cold["scheduler"])
        torch.set_rng_state(cold["rng"])
        if device=="cuda":
            torch.cuda.set_rng_state_all(cold["cuda_rng"])
        epoch,updates,elapsed,best,curve=(cold[k] for k in ("epoch","updates","elapsed","best","curve"))
        presents.update(cold["presents"])
    else:
        curve.append(dict(epoch=0,validation=measure()))
    bf16=device=="cuda" and torch.cuda.is_bf16_supported()
    if device=="cuda":
        torch.cuda.reset_peak_memory_stats()
    for number in range(epoch+1,min(cfg["epochs"],until or cfg["epochs"])+1):
        tick=perf_counter()
        rng=np.random.default_rng([cfg["seed"],number])
        net.train()
        losses_epoch=torch.zeros(2,device=device)
        for _ in range(cfg["updates_per_epoch"]):
            blocks=[train[name].take(n,rng) for name,n in nominal.items()]
            batch=merge(blocks,device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda",dtype=torch.bfloat16) if bf16 else nullcontext():
                predicted=net(batch,chosen_only=True)
            terms=[losses(net,output,batch) for output in predicted]
            loss=sum((nll+.04*growth).mean() for nll,growth in terms)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(),1.)
            optimizer.step()
            losses_epoch+=torch.stack([nll.detach().mean() for nll,_ in terms])
            presents.update({name:len(block["cls"]) for name,block in zip(nominal,blocks,strict=True)})
            updates+=1
        observed=measure()
        rank=sum(n*(m["overall"]["v"]["nll"]+m["overall"]["q"]["nll"])
                 for (name,n),m in zip(nominal.items(),observed.values(),strict=True))/cfg["batch"]
        if not np.isfinite(rank):
            raise FloatingPointError("Nonfinite validation")
        schedule.step()
        elapsed+=perf_counter()-tick
        entry=dict(epoch=number,validation=observed,score=rank,elapsed=elapsed,
                   train_nll=(losses_epoch/cfg["updates_per_epoch"]).tolist())
        curve.append(entry)
        improved=rank<best
        if improved:
            best=rank
        state=dict(identity=identity,epoch=number,model=net.state_dict(),optimizer=optimizer.state_dict(),
                   scheduler=schedule.state_dict(),updates=updates,elapsed=elapsed,best=best,curve=curve,
                   presents=dict(presents),rng=torch.get_rng_state(),
                   cuda_rng=torch.cuda.get_rng_state_all() if device=="cuda" else [])
        if improved:
            atomic_save(out/"best-train.pt",state)
            atomic_save(out/"best.pt",dict(version=VERSION,model=net.state_dict(),sources=contract(),
                        spec=saved["spec"],vocabulary=saved["vocabulary"],policies=registry,epoch=number,identity=identity))
        atomic_save(checkpoint,state)
        write_json(out/"summary.json",dict(epochs=number,updates=updates,presents=presents,elapsed=elapsed,
            peak_cuda_bytes=torch.cuda.max_memory_allocated() if device=="cuda" else None,
            policies=registry,slot=new_slot,curve=curve,sha=checksum(out/"best.pt")))
        print(out.name,number,rank,updates,dict(presents),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("history","current","parent","optimizer","output"):
        parser.add_argument(name,type=Path)
    parser.add_argument("--previous",type=Path)
    parser.add_argument("--device",choices=("cpu","cuda"),default="cuda")
    parser.add_argument("--until",type=int)
    args=parser.parse_args()
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("high")
    fit(args.history,args.current,args.previous,args.parent,args.optimizer,args.output,config(),args.device,args.until)
