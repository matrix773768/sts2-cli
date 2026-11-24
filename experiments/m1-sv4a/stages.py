"""Run both official generations, freeze the final candidate matrix, and compare pairs."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from loop_common import HERE, ROOT, checksum, digest, sources, write_json
from loop_battle import read_ledger, run
from loop_learn import prepare


def read(path):
    return json.loads(path.read_bytes())


def learn(output, cfg, stage, parent, optimizer, device):
    dataset = output/"features"/stage
    prepare(output/"experience"/stage, output/"roots"/f"{stage}.json", dataset, parent,cfg)
    destination = output/"models"/stage
    destination.mkdir(parents=True,exist_ok=True)
    previous = output/"features"/f"{stage[0]}1" if stage.endswith("2") else None
    python = ROOT/"logs/m1-pre1-cuda/Scripts/python.exe" if device=="cuda" else Path(sys.executable)
    command = [str(python),"-X","utf8",str(HERE/"loop_learn.py"),str(ROOT/cfg["history"]),
               str(dataset),str(parent),str(optimizer),str(destination),"--device",device]
    if previous:
        command += ["--previous",str(previous)]
    previous_run = destination/"summary.json"
    with (destination/"train.log").open("a",encoding="utf-8") as log:
        if stage=="D1" and not (destination/"resume.pt").exists():
            subprocess.run(command+["--until","1"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            proof=read(previous_run)
            write_json(destination/"interruption-proof.json",dict(epochs=proof["epochs"],updates=proof["updates"],
                       peak_cuda_bytes=proof["peak_cuda_bytes"],state=checksum(destination/"resume.pt")))
        if not previous_run.exists() or read(previous_run)["epochs"]<cfg["epochs"]:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=read(previous_run)
    if (result["epochs"]!=cfg["epochs"] or result["updates"]!=cfg["epochs"]*cfg["updates_per_epoch"]
            or result["sha"]!=checksum(destination/"best.pt")):
        raise ValueError("Incomplete or changed official generation checkpoint")
    return destination/"best.pt", destination/"best-train.pt", read(dataset/"manifest.json")["policy"]


def summarize(output,matrix):
    columns={}
    comparisons = [
        ("S0","D0"),("D1","D0"),("D2","D0"),("D2","D1"),("S1","S0"),("S2","S0"),("S2","S1"),
        ("D2-search","D2"),("S2","S2-direct"),("S2-direct","D2"),("S2-A2","D2-A2"),
        ("D0","A2"),("S2","A2"),
    ]
    for phase in ("development","confirmation"):
        directory=output/"evaluation"/phase
        rows={name:list(read_ledger(directory/name,full=False)) for name in matrix}
        roots=read(output/"roots"/f"{phase}.json")["jobs"]
        for name, items in rows.items():
            if len(items)!=len(roots) or any(r["ordinal"]!=i for i,r in enumerate(items)):
                raise ValueError(f"Missing or reordered paired roots in {name}")
        phase_results={}
        for current, base in comparisons:
            changed, base_rows=rows[current],rows[base]
            delta, hp=[], []
            flips=Counter()
            for a,b in zip(changed,base_rows,strict=True):
                left,right=a["row"],b["row"]
                if left["root"]!=right["root"] or left["family"]!=right["family"]:
                    raise ValueError("Paired comparison root differs")
                win, old = left["status"]=="predicted_win",right["status"]=="predicted_win"
                delta.append(int(win)-int(old))
                flips["death_to_win"]+=win and right["status"]=="death"
                flips["win_to_death"]+=old and left["status"]=="death"
                if win and old:
                    hp.append(right["terminal"]["hp"]-left["terminal"]["hp"])
            rng=np.random.default_rng(71394211)
            interval=np.quantile(rng.choice(delta,size=(4000,len(delta))).mean(1),[.025,.975]).tolist()
            hp_interval=(np.quantile(rng.choice(hp,size=(4000,len(hp))).mean(1),[.025,.975]).tolist()
                         if hp else None)
            phase_results[f"{current}_vs_{base}"]=dict(delta=float(np.mean(delta)), ci95=interval,
                flips=flips,joint_wins=len(hp), joint_win_loss_delta=float(np.mean(hp)) if hp else None,
                joint_win_loss_ci95=hp_interval)
        columns[phase]=dict(paired=phase_results, arms={name:read(directory/name/"summary.json") for name in matrix})
    write_json(output/"paired.json",columns)


def diagnostics(host,output,cfg,initial,selection,matrix):
    path=output/"diagnostics"
    path.mkdir(exist_ok=True)
    origin=read(ROOT/"logs/m1-sv3a-roots/confirmation.json")
    cases=origin["jobs"]
    source=path/"owl.json"
    write_json(source,dict(config=origin["config"],purpose="historical_fixed_world_owl",jobs=[cases[63]]))
    variants={
        "cascade-A2":(*matrix["A2"],"Cascade"),
        "cascade-D0":(*matrix["D0"],"Cascade"),
        "endturn-D0":(*matrix["D0"],"EndTurn"),
        "cascade-S0":(*matrix["S0"],"Cascade"),
        "cascade-D2":(*matrix["D2"],"Cascade"),
        "cascade-S2":(*matrix["S2"],"Cascade"),
    }
    for name,(model,condition,budget,first) in variants.items():
        run(host,source,path/name,cfg,model,condition,budget,forced=first)
    long_path=path/"long.json"
    write_json(long_path,dict(config=origin["config"],purpose="historical_fixed_world_long",jobs=[cases[i] for i in (48,268)]))
    for name in ("D0","S0","D2","S2"):
        run(host,long_path,path/f"long-{name}",cfg,*matrix[name])


def stages(host,output,cfg,selection,initial,device,route_filter="both"):
    budget=selection["budget"]
    g0, g0_optimizer = ROOT/cfg["g0"], ROOT/cfg["g0_resume"]
    matrix={"A2":(None,None,0),"D0":(g0,initial,0),"S0":(g0,initial,budget)}
    development=output/"roots/development.json"
    proof={}
    def evaluate(name,weights,condition,budget):
        return run(host,development,output/"evaluation/development"/name,cfg,weights,condition,budget)

    # Evaluate the generation before collecting from it, with all held-out confirmation results still unopened.
    for route in "DS" if route_filter=="both" else route_filter:
        parent, optimizer, continuation = g0,g0_optimizer,initial
        previous=route+"0"
        previous_budget=0 if route=="D" else budget
        evaluate(previous,parent,continuation,previous_budget)
        for number in (1,2):
            stage=f"{route}{number}"
            attempts=selection["search_attempts"] if route=="S" else cfg["experience_roots"][stage]
            report=run(host,output/"roots"/f"{stage}.json",output/"experience"/stage,cfg,parent,continuation,
                previous_budget,epsilon=cfg["exploration"],attempts=attempts)
            if report["attempts"]!=attempts:
                raise ValueError("Incomplete experience execution")
            parent,optimizer,continuation=learn(output,cfg,stage,parent,optimizer,device)
            matrix[stage]=(parent,continuation,previous_budget)
            evaluate(stage,*matrix[stage])
            proof[stage]=dict(behavior=read(output/"features"/stage/"manifest.json")["definition"],complete=report["complete"],
                checkpoint=checksum(parent),condition=continuation)
    if route_filter!="both":
        return
    matrix["D2-search"]=(*matrix["D2"][:2],budget)
    matrix["S2-direct"]=(*matrix["S2"][:2],0)
    matrix["D2-A2"]=(matrix["D2"][0],initial,0)
    matrix["S2-A2"]=(matrix["S2"][0],initial,0)
    for name in ("A2","D2-search","S2-direct","D2-A2","S2-A2"):
        evaluate(name,*matrix[name])
    path=output/"candidate-lock.json"
    registration=dict(arms={name:dict(weight=checksum(weights) if weights else None,
                        condition=condition,budget=limit)
                        for name,(weights,condition,limit) in matrix.items()},
                    generations=proof,selection=checksum(output/"selection.json"),
                    confirmation=checksum(output/"roots/confirmation.json"),
                    sources=sources("loop_policy.py","loop_battle.py","loop_learn.py","stages.py"))
    if path.exists():
        if read(path)!=registration:
            raise ValueError("Confirmation candidates already frozen with a different identity")
    else:
        write_json(path,registration)
    for name,(weight,condition,limit) in matrix.items():
        run(host,output/"roots/confirmation.json",output/"evaluation/confirmation"/name,cfg,weight,condition,limit)
    summarize(output,matrix)
    diagnostics(host,output,cfg,initial,selection,matrix)
