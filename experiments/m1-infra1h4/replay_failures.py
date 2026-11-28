"""Replay each actual H3 failure at its original action, including its sealed G2 encoder."""
import gzip
import json
import subprocess
import sys
import types
from pathlib import Path
from diagnose import HERE,ROOT,diff
from client import Client
from models import strategic,return_law,boundary_key
from release import pack

START="21df7b60e836c663e82e44b8c353200e6a72b22f"

def encoder():
    text=subprocess.check_output(["git","show",START+":engine/HotSearch/models.py"],cwd=ROOT)
    module=types.ModuleType("h3_frozen_model_inputs")
    module.__file__=str(ROOT/"engine/HotSearch/models.py")
    exec(compile(text,module.__file__,"exec"),module.__dict__)
    return module

def reference(client,old,models,h,hist,opening,first):
    memory={0:models.g2.encoder.update(hist,h,h["actions"][first])}
    reply=client.engine.send(dict(op="search",indices=[first],limit=32,g2=True))
    while reply["type"]=="g2":
        obs=old.choice_b(reply["facts"],reply["prompt"]) if reply["prompt"] else old.public_b(reply["facts"])
        parent=memory[reply["parent"]];pick=models.rank(obs,parent,opening)[0];ticket=reply["ticket"]
        memory[ticket]=models.g2.encoder.update(parent,obs,obs["actions"][pick])
        reply=client.engine.send(dict(op="g2",ticket=ticket,index=pick))
    if not reply["ok"]:raise ValueError(reply["reason"])
    return reply["result"][0]

def run(out):
    out.mkdir(exist_ok=False,parents=True);old=encoder();models=old.Models();client=Client(out/"transport")
    specs=json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
    audit=[]
    try:
        for r in map(json.loads,gzip.open(ROOT/"experiments/m1-infra1h3r/evidence/strict.jsonl.gz")):
            if r["terminal"]:continue
            i=r["i"];q=r["queries"][-1];s=specs[i]["spec"];target=q["turn"]
            rec=dict(i=i,turn=target,encounter=r["encounter"],h3_reason=r["reason"],first=q.get("selected"))
            audit.append(rec);graph=None;picks=0
            try:
                step=client.call("open",spec=s);hist=models.g2.encoder.initial_history()
                for t,(turn,index,kind,slot,foe,side) in enumerate(r["trace"]):
                    f=step["facts"];h=old.public_b(f);before=r["boundaries"][t]
                    visible=(f["hp"],f["block"],f["energy"],[[c["id"],c["upgrade"]] for c in f["hand"]])
                    if visible!=(before["hp"],before["block"],before["energy"],before["hand"]):raise ValueError("historical visible prefix diverged at "+str(t))
                    if turn==target and graph is None and q.get("matched") is False:
                        if index!=q["selected"]:raise ValueError("turn root first action")
                        graph=client.call("search",indices=[index],limit=32)[0] if q["committed"] else reference(client,old,models,h,hist,s,index)
                        rec["gaps"]=graph["gaps"];rec["law"]=return_law(graph)
                        edges={(e["parent"],e["view"]):e for e in graph["policy"]};node=0
                    def binding(st,pick):
                        nonlocal node,picks
                        edge=edges.get((node,st["view"]))
                        if not edge or edge["index"]!=pick:return False
                        node=edge["node"];picks+=1;return True
                    if graph and not binding(step,index):rec.setdefault("policy_divergence",t)
                    hist=models.g2.encoder.update(hist,h,h["actions"][index]);step=client.call("step",index=index)
                    for choice in (v for v in r["choices"] if v["at"]==t):
                        if step.get("options")!=choice["options"]:raise ValueError("historical choice menu")
                        pick=choice["selected"];obs=old.choice_b(step["facts"],step)
                        if graph and not binding(step,pick):rec.setdefault("policy_divergence",t)
                        hist=models.g2.encoder.update(hist,obs,obs["actions"][pick]);step=client.call("step",index=pick)
                rec["status"]=step["status"];rec["matched_actions"]=len(r["trace"]);rec["program_steps"]=picks
                c=step.get("observed_c")
                if c:
                    obj=strategic(c["facts"],c["draw"]);rec["actual"]=obj;rec["observed"]=boundary_key("C",obj)
                elif step["status"] in ("Victory","Defeat"):rec["observed"]=boundary_key(step["status"],step["facts"])
                if graph:rec["matched"]=rec.get("observed") in rec["law"] and not graph["gaps"] and "policy_divergence" not in rec
            except (KeyError,ValueError,IndexError,RuntimeError) as e:rec.update(status="failed",reason=str(e))
    finally:client.close()
    pack(out/"replay.jsonl.gz",audit)

if __name__=="__main__":run(Path(sys.argv[1]))
