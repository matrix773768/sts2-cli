"""Final analyses after excluding the entire unqualified Knowledge Demon encounter."""
import gzip
import json
from collections import Counter
from pathlib import Path
import sys

import numpy as np
from analyze import entries, read
from arena import ROOT, PARENT, Controller, Policy, CFG, checksum, digest, load, manifest
from dc_metrics import describe, paired
from learn import restore, metrics, records
from features import Encoder
from value import torch


def run(out):
    logs=ROOT/"logs"
    torch.set_num_threads(1)
    families={}
    battles, differences, examples = {}, {}, []
    for group in ("primary","fresh"):
        jobs={j[0]:j for j in manifest(group=="fresh")["jobs"] if
              j[2]=="report" and j[1]["encounter"]!="KNOWLEDGE_DEMON_BOSS"}
        families[group]=[j[3] for j in jobs.values()]
        for budget in (0,24):
            arms={}
            for name in (("frozen","base","mech") if group=="primary" else ("frozen","base","mech","wide")):
                path=logs/f"n1bc-clean-{group}-{name}-{budget}"
                if group=="primary" and name=="frozen":
                    path=logs/f"n1bc-eval-frozen-{budget}"
                items={e["ordinal"]:e for e in entries(path) if e["ordinal"] in jobs}
                if set(items)!=set(jobs):
                    raise ValueError(f"Missing paired roots in {path}")
                arm=arms[name]=[items[i]["row"] for i in jobs]
                for i,r in zip(jobs,arm,strict=True):
                    if r["family"]!=jobs[i][3] or r["root"]!={k:v for k,v in jobs[i][1].items() if k!="seed"}:
                        raise ValueError("Root drift")
                counts=Counter()
                for e in items.values():
                    counts.update(e["counts"])
                battles[f"{group}-{budget}-{name}"]=describe(arm) | dict(counts=counts,
                    wall_s=sum(e["wall_s"] for e in items.values()),actions=sum(r["length"] for r in arm))
            for a,b in (("frozen","base"),("base","mech"),*((("base","wide"),("mech","wide")) if "wide" in arms else ())):
                pairs=list(zip(arms[a],arms[b],strict=True))
                key=f"{group}-{budget}-{a}-{b}"
                differences[key]=paired(pairs,bootstrap=True)
                for j,(r,s) in zip(jobs,pairs,strict=True):
                    if r["status"]!=s["status"] or (r["terminal"] or {}).get("hp")!=(s["terminal"] or {}).get("hp"):
                        divergence=next((i for i,(l,m) in enumerate(zip(r["steps"],s["steps"]))
                                         if l["action"]!=m["action"]),None)
                        examples.append(dict(pair=key,ordinal=j,encounter=r["root"]["encounter"],
                             outcomes=[r["status"],s["status"]],end_hp=[r["terminal"]["hp"],s["terminal"]["hp"]],
                             first_difference=divergence))
    if set(families["primary"]) & set(families["fresh"]):
        raise ValueError("Repeated report family")
    source=logs/"n1bc-cohort"
    baseline,meta=load(PARENT)
    slot=meta["policies"].index(meta["deployment"])
    batches,_=records(source,Encoder(meta["vocabulary"]),slot,digest(read(source/"run.json")["definition"]),True)
    scores={"frozen":metrics(baseline,batches["report"])}
    for name in ("base","mech","wide"):
        scores[name]=read(logs/f"n1bc-clean-{name}/result.json")["report"]
    top={k:v.pop("top") for k,v in scores.items()}
    ranking=read(logs/"n1bc-ranking/ranking.json")
    ids={j[0] for j in manifest()["jobs"] if j[3] in families["primary"]}
    pairs=[r for r in ranking["roots"] if r["ordinal"] in ids and
           "utility" in r and r["utility"][0]!=r["utility"][1]]
    rank={}
    for name in ("frozen","base","mech","wide"):
        model=Policy(PARENT,meta["deployment"],0,0.,{},CFG)
        if name!="frozen":
            model.net,model.encoder,model.slot=restore(logs/f"n1bc-clean-{name}/model.pt")
        correct=[]
        for r in pairs:
            with gzip.open(logs/f"n1bc-ranking/{r['ordinal']}-0.json.gz") as f:
                obs=json.load(f)["row"]["steps"][0]["observation"]
            c=Controller(model,None,lambda rows:next(model.forward([(rows,)])),None)
            c.initial_hp,c.initial_max=obs["hp"],obs["max_hp"]
            q=c.score([(obs,c.history)])[0][0][r["actions"]]
            correct.append(bool(np.sign(q[0]-q[1])==np.sign(r["utility"][0]-r["utility"][1])))
        rank[name]=dict(correct=sum(correct),informative=len(correct),attempts=len(ids))
    output=dict(families=families,battles=battles,comparisons=differences,outcome_changes=examples,offline=scores,
        rank=rank,top_changes={n:sum(i!=j for i,j in zip(v,top["base"],strict=True)) for n,v in top.items()})
    out.write_text(json.dumps(output,indent=2,allow_nan=False))


if __name__=="__main__":
    run(Path(sys.argv[1]))
