"""Measure action support against the frozen PRE1 reference without changing play."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import random
import sqlite3
from pathlib import Path

import numpy as np
import torch

from loop_common import ROOT, checksum, write_json
from sv_data import Encoder, decoded
from sv_runtime import tensors
from train import load_policy


@torch.inference_mode()
def score(model, rows):
    feature, modes, chosen = zip(*rows, strict=True)
    logits = model(tensors(feature, "cpu"))
    probabilities = logits.softmax(1)
    for row, mode, index in zip(probabilities, modes, chosen, strict=True):
        chosen_probability = float(row[index])
        ranked = row.argsort(descending=True, stable=True)[:3].tolist()
        yield mode, chosen_probability, index not in ranked


def analyze(model, encoder, output, seed):
    rng = random.Random(seed)
    uri = (output / "results.sqlite").resolve().as_uri() + "?mode=ro"
    pool, label, stats, actions, n_roots = [], defaultdict(list), Counter(), Counter(), 0
    def accumulate():
        for mode, p, out in score(model, pool):
            label["all"].append((p,out))
            if mode!="all":
                label[mode].append((p,out))
        pool.clear()
    with closing(sqlite3.connect(uri,uri=True)) as db:
        ids = [ordinal for ordinal, in db.execute("SELECT ordinal FROM results ORDER BY ordinal")]
        subset = rng.sample(ids,min(256,len(ids)))
        for ordinal in subset:
            expected, blob = db.execute("SELECT sha,payload FROM results WHERE ordinal=?",(ordinal,)).fetchone()
            row = decoded(expected,blob)["row"]
            if not row["steps"]:
                continue
            n_roots+=1
            history=encoder.initial_history()
            selected=set(rng.sample(range(len(row["steps"])),min(4,len(row["steps"]))))
            for i,step in enumerate(row["steps"]):
                obs, move=step["observation"],step["action"]
                actions[move["kind"]]+=1
                if i in selected:
                    pool.append((encoder.encode(obs,history),step["mode"],move["index"]))
                    if len(pool)>=128:
                        accumulate()
                history=encoder.update(history,obs,move)
            stats[row["status"]]+=1
    if pool:
        accumulate()
    result={}
    for mode, pairs in label.items():
        probability,out=np.array(pairs).T
        result[mode]=dict(n=len(pairs),below_05=int((probability<.05).sum()),
                          outside_top3=int(out.sum()),mean=float(probability.mean()))
    return dict(subset_roots=n_roots,outcomes=stats,actual_action_modes=actions,support=result,
                ledger=checksum(output/"results.sqlite"))


def audit(root, output, include_confirmation):
    prior=ROOT/"logs/m1-pre1-campaign/weights/final.pt"
    model,vocab=load_policy(prior)
    encoder=Encoder(vocab)
    directories=list((root/"experience").iterdir())
    if include_confirmation:
        directories.extend((root/"evaluation/confirmation").iterdir())
    result={path.relative_to(root).as_posix():analyze(model,encoder,path,71394302)
            for path in sorted(directories) if (path/"summary.json").exists()}
    write_json(output,dict(prior=checksum(prior),groups=result))


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("campaign",type=Path)
    cli.add_argument("output",type=Path)
    cli.add_argument("--confirmation",action="store_true")
    args=cli.parse_args()
    torch.set_num_threads(2)
    audit(args.campaign,args.output,args.confirmation)
