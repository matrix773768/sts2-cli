"""Aggregate paired battles, calibration, feature coverage and warmed one-state latency."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter

import numpy as np
from arena import ROOT, PARENT, checksum, digest, load, manifest, tensors, torch
from learn import records, metrics, restore
from mechanics import PilotEncoder, catalogs, card_info
from dc_metrics import describe, paired
from features import Encoder


def read(path):
    return json.loads(path.read_bytes())


def entries(folder):
    for p in sorted(folder.glob("*.json.gz")):
        with gzip.open(p) as f:
            yield json.load(f)


def measure(net, enc, slot, observations):
    timing=[]
    with torch.inference_mode():
        for o in observations[:6]+observations*3:
            t=perf_counter()
            row=enc.encode(o,enc.initial_history()) | dict(policy=slot)
            net(tensors([row],"cpu"))
            timing.append((perf_counter()-t)*1000)
    timing=timing[6:]
    return dict(n=len(timing),p50=float(np.median(timing)),p90=float(np.quantile(timing,.9)))


def summarize(out):
    logs=ROOT/"logs"
    data=logs/"n1bc-cohort"
    torch.set_num_threads(1)
    net,meta=load(PARENT)
    teacher=read(data/"run.json")
    slot=meta["policies"].index(meta["deployment"])
    enc=Encoder(meta["vocabulary"])
    rows,_=records(data,enc,slot,digest(teacher["definition"]))
    report=metrics(net,rows["report"])
    training={}
    top={"frozen":report.pop("top")}
    states=[]
    coverage=Counter()
    cards,species,encounters,stacks,rooms=set(),set(),set(),Counter(),Counter()
    thickness,turns,menus=[],[],[]
    for item in entries(data):
        r=item["row"]
        states.append(r["steps"][len(r["steps"])//2]["observation"])
        thickness.append(len(r["root"]["deck"]))
        encounters.add(r["root"]["encounter"])
        rooms[r["room"]]+=1
        for s in r["steps"]:
            o=s["observation"]
            turns.append(o["turn"])
            menus.append(len(o["actions"]))
            m=o["mechanism"]
            species.update(m["species"])
            stacks.update(e["id"] for e in m["stacks"])
            coverage.update(states=1,nonzero_played=int(m["played"]!=0),extra_power=int(bool(m["stacks"])),
                            choice=int(o["decision"]["phase"]=="choice"),relics=int(bool(o["relics"])),
                            multi_enemy=int(len(o["enemies"])>1),midturn=int(o["turn"]>1))
            for wide in (False,True):
                label="wide" if wide else "initial"
                table,graphs=catalogs(wide)
                for name in m["species"]:
                    coverage[label+"_enemy_graph"]+=int(name in graphs)
                for c in o["hand"]:
                    name=c["id"]
                    cards.add(name)
                    base,_=card_info(name,c["upgrade"],wide)
                    coverage[label+"_card_rule"]+=int(name in table)
                    coverage[label+"_cost_delta"]+=int(base is not None and base>=0 and c["cost"] is not None and base!=c["cost"])
            coverage.update(enemy_slots=len(m["species"]),hand_slots=len(o["hand"]))
    latency={"frozen":measure(net,enc,slot,states[::3])}
    training["frozen"]=dict(parameters=sum(p.numel() for p in net.parameters()),report=report)
    for arm in ("base17","mech17","base29","mech29","wide17"):
        directory=logs/("n1bc-"+arm)
        training[arm]=read(directory/"result.json")
        top[arm]=training[arm]["report"].pop("top")
        if arm in ("base17","mech17","wide17"):
            model,encoder,condition=restore(directory/"model.pt")
            latency[arm]=measure(model,encoder,condition,states[::3])
    battles,comparisons,raw={}, {}, {}
    for split,arms in (("eval",("frozen","base17","mech17","base29","mech29")),
                       ("fresh",("base17","mech17","wide17"))):
        source=manifest(split=="fresh")
        for budget in (0,24):
            for arm in arms:
                key=f"{split}-{arm}-{budget}"
                directory=logs/("n1bc-"+key)
                timing=read(directory/"run.json")
                items=list(entries(directory))
                if len(items)!=40:
                    raise ValueError(key)
                for entry in items:
                    j=source["jobs"][entry["ordinal"]]
                    r=entry["row"]
                    if j[3]!=r["family"] or r["root"]!={k:v for k,v in j[1].items() if k!="seed"}:
                        raise ValueError("Unpaired root")
                raw[key]=[e["row"] for e in items]
                counts=Counter()
                for e in items:
                    counts.update(e["counts"])
                battles[key]=dict(seconds=timing["seconds"],counts=counts,**describe(raw[key]))
            for a,b in ([("base17","mech17"),("base29","mech29"),("frozen","base17")] if split=="eval"
                        else [("base17","wide17"),("mech17","wide17")]):
                pairs=list(zip(raw[f"{split}-{a}-{budget}"],raw[f"{split}-{b}-{budget}"],strict=True))
                comparisons[f"{split}-{a}-{b}-{budget}"]=paired(pairs,bootstrap=True)
    rank=read(logs/"n1bc-ranking/ranking.json")
    useful=[r for r in rank["roots"] if "utility" in r and r["utility"][0]!=r["utility"][1]]
    ranking={k:sum(np.sign(r["predictions"][k][0]-r["predictions"][k][1])==
                    np.sign(r["utility"][0]-r["utility"][1]) for r in useful).item() for k in top if k!="wide17"}
    result=dict(coverage=coverage,cards=len(cards),species=len(species),encounters=len(encounters),
                powers=stacks,rooms=rooms,deck_range=[min(thickness),max(thickness)],max_turn=max(turns),
                menu=[min(menus),median(menus),max(menus)],teacher_seconds=teacher["seconds"],
                teacher_counts=teacher["counts"], training=training, latency_ms=latency,
                battles=battles,comparisons=comparisons,ranking=dict(non_ties=len(useful),correct=ranking),
                report_top_disagreement={s:sum(a!=b for a,b in zip(top["base"+s],top["mech"+s],strict=True))
                                         for s in ("17","29")})
    out.write_text(json.dumps(result,indent=2,allow_nan=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    summarize(parser.parse_args().output)
