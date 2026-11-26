"""Fixed signed feature hashing of public mechanisms; no root IDs, seed or terminal features."""
from functools import lru_cache
import hashlib,math
import numpy as np
from experience import HERE
from state import static_rules
import torch
from torch import nn
from value import CENTERS,expected,targets,payoff

D=1024
@lru_cache(16000)
def slot(key):
    v=int.from_bytes(hashlib.blake2s(key.encode(),digest_size=4).digest(),"little")
    return v%D,1 if v&(1<<31) else -1

def features(c,arm,omit=None):
    foes=[e for e in c["enemies"] if e["hp"]>0]
    nums=[c["hp"],c["max_hp"],c["hp"]/c["max_hp"],c["turn"],sum(e["hp"] for e in foes),
        sum(sum(e["attack_hits"]) for e in foes),len(foes),c["energy"],c["block"],c["stars"],
        c["draw_count"],len(c["deck"]),len(c["exhaust"]),len(c["hand"]),len(c["discard"]),c["setup"]["draw"]]
    x=np.zeros(len(nums)+(0 if arm=="simple" else D),dtype=np.float32)
    x[:len(nums)]=np.log1p(nums)
    if arm=="simple":return x
    def add(parts,v=1):
        category=("enemy" if parts[0] in ("foe","intent","register","foe_power","hit","effect","condition","edge")
                  else "player" if parts[0] in ("power","trigger","relic") else "cards")
        if category==omit:return
        i,sign=slot("|".join(map(str,parts)))
        x[len(nums)+i]+=sign*math.copysign(math.log1p(abs(v)),v)
    rules=static_rules()
    for e in foes:
        species=e["species"];move=e.get("move");phase=e.get("phase",{})
        add(("foe",species),e["hp"]);add(("intent",species,move),1+sum(e["attack_hits"]))
        for k,v in phase.get("registers",{}).items():add(("register",species,k),v)
        for p in e["powers"]:add(("foe_power",species,p["id"]),p["amount"])
        nodes={n["MoveId"]:n for n in rules["graphs"].get(species,[])}
        queue=[(move,0)];seen=set()
        while queue:
            key,depth=queue.pop()
            if key in seen or key not in nodes or depth>3:continue
            seen.add(key);n=nodes[key];weight=1/(1+depth)
            for a in n["attacks"]:add(("hit",species,key,a["Repeats"]),weight*a["BaseDamage"])
            for ef in n["effects"]:add(("effect",key,ef["Op"],ef.get("power")),weight*ef["Amount"])
            if n.get("condition"):add(("condition",key,str(n["condition"])),weight)
            windows={w["target"]:w["allowed_by_history"] for w in phase.get("repeat_windows",{}).get(key,[])}
            for child in n["targets"]+([n["next"]] if n.get("next") else []):
                add(("edge",key,child,windows.get(child)),weight)
                if windows.get(child,True):queue.append((child,depth+1))
    for p in c["powers"]:
        add(("power",p["id"]),p["amount"])
        add(("trigger",rules["powers"].get(p["id"],{}).get("HookMask")),p["amount"])
    for r in c["relics"]:add(("relic",r["id"]),1+(r.get("counter") or 0))
    for zone,cards in c["card_state"].items():
        for card in cards:
            name=card["type"];add((zone,name));add(("cost",zone,name),card["cost"])
            for resource,layers in card.get("cost_layers",{}).items():
                for i,layer in enumerate(layers):add(("layer",resource,name,i,str(sorted(layer.items()))))
            for k,v in card["vars"].items():add(("var",zone,k),v)
    for key,count in c["belief"]["counts"].items():add(("bag",key),count)
    for z in ("top","bottom"):
        for i,key in enumerate(c["belief"][z]):add((z,i,key))
    return x

def network(arm):
    return nn.Sequential(nn.Linear(16+(0 if arm=="simple" else D),96),nn.LayerNorm(96),nn.SiLU(),
        nn.Linear(96,64),nn.SiLU(),nn.Linear(64,1+len(CENTERS)))

def predict(net,arm,states,h):
    with torch.no_grad():
        probs=net(torch.from_numpy(np.stack([features(c,arm) for c in states]))).softmax(-1)
        return expected(probs,torch.tensor(h["hp"]),torch.tensor([c["hp"] for c in states]),
                        torch.tensor(h["max_hp"])).tolist()
