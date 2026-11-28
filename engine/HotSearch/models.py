"""Frozen, CPU-only weights. Only public model features enter this module."""

import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"experiments/m1-core5a"))


from search5 import Evaluator
from semantic import Value, payoff, torch, cohort
from features import variant


def card(c,index,cost=False):
    r=dict(index=index,id=c["id"],upgrade=c["upgrade"])
    for key in ("enchantment","affliction"):
        if c.get(key):
            r[key]=c[key]
            r[key+"_amount"]=c[key+"_amount"]
    if cost:r["cost"]=c["cost"]
    return r


def token(c):
    return c["id"]+"#"+str(c["upgrade"])


def public_b(f):
    h={k:f[k] for k in ("turn","hp","max_hp","block","energy","stars","draw_count","powers")}
    h.update(decision=dict(phase="combat"),relics=[],potions=[None]*f["potion_slots"])
    for zone in ("hand","discard","exhaust","deck"):
        pile=f[zone] if zone in ("hand","discard") else sorted(f[zone],key=token)
        h[zone]=[card(c,i,zone=="hand") for i,c in enumerate(pile)]
    h["enemies"]=[dict(index=i,hp=e["hp"],block=e["block"],attack_hits=e["attack_hits"],
        intents=e.get("intents",["Attack"] if e["attack_hits"] else []),powers=e["powers"]) for i,e in enumerate(f["enemies"])]
    h["actions"]=[]
    for a in f["actions"]:
        play=a["kind"]=="PlayCard"
        if not play and a["kind"]!="EndTurn":raise ValueError("unhandled menu "+a["kind"])
        c=f["hand"][a["card"]] if play else {}
        preview={}
        if play:
            _,details=variant(c["id"],c["upgrade"])
            for effect in details.get("effects",[]):
                if effect.get("kind")=="Damage":
                    preview.update(damage_per_hit=c["damage"],hits=c["hits"])
                if effect.get("kind")=="Block":preview["block"]=c["block"]
                if effect.get("kind")=="Draw" and "Cards" in c["vars"]:preview["draw"]=c["vars"]["Cards"]
        h["actions"].append(dict(index=a["index"],kind="play_card" if play else "end_turn",
            card=a["card"] if play else None,target=a["target"],target_side=a["target_side"],
            cost=c.get("cost"),choice=None,energy_x=c.get("energy_x",False),preview=preview))
    return h


def choice_b(f,prompt):
    h=public_b(f)
    indexes=[];cards=[]
    for option in prompt["options"]:
        if option=="skip":
            indexes.append(None)
        else:
            name,up=option.rsplit("#",1);indexes.append(len(cards))
            cards.append(dict(index=len(cards),id=name,upgrade=int(up)))
    h["decision"]=dict(phase="choice",pile=prompt["kind"],min=int(None not in indexes),max=1,candidates=cards,selected=[])
    h["actions"]=[dict(index=i,kind="confirm_selection" if slot is None else "select_candidate",card=None,
        choice=slot,target=None,target_side=None,cost=None,preview=None) for i,slot in enumerate(indexes)]
    return h


def strategic(f,draw):
    c={k:f[k] for k in ("turn","round","hp","max_hp","block","energy","stars","gold","draw_count","powers","enemies","belief")}
    c["enemies"]=f["known_enemies"]
    c["belief"]=dict(f["belief"])
    c.update(schema="sts2.core.c.v3",deck=[card(r,i) for i,r in enumerate(sorted(f["deck"],key=token))],relics=[],potions=[None]*f["potion_slots"],
             enemy_models=[],events=[],card_state={})
    for z in ("hand","discard","exhaust"):
        rows=f[z] if z=="hand" else sorted(f[z],key=token)
        c[z]=[card(r,i,z=="hand") for i,r in enumerate(rows)]
        c["card_state"][z]=[dict(type=token(r),cost=r["cost"],vars=r["vars"],cost_layers=r.get("cost_layers",{})) for r in rows]
    c["setup"]=dict(stage="before_initial_draw",draw=draw,will_shuffle=f["draw_count"]<draw,
        side_started=False,extra_turn=False,completed=["enemy_side","before_hand_draw","modified_draw_count"],
        pending=["hand_draw","draw_hooks","after_player_start","side_start","deaths_orbs_autoplay"])
    return c


def boundary_key(status,state):
    if status=="C":
        payload=[state,list(state["belief"]["counts"])]
    else:
        payload=[status,state["hp"],state["max_hp"],state["gold"]]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def return_law(graph):
    mass={}
    for leaf in graph["leaves"]:
        c=strategic(leaf["facts"],leaf["draw"]) if leaf["kind"]=="C" else leaf
        k=boundary_key(leaf["kind"],c)
        mass[k]=mass.get(k,0.)+leaf["mass"]
    return mass


class Models:
    def __init__(self):
        torch.set_num_threads(1)
        if cohort.checksum(cohort.PARENT)!=cohort.PARENT_SHA:raise ValueError("G2 identity")
        _,meta=cohort.load(cohort.PARENT)
        self.g2=cohort.Policy(cohort.PARENT,meta["deployment"],0,0.,"HotSearch",cohort.CFG)
        v2=ROOT/"experiments/m1-core5a/evidence/v2.pt"
        if cohort.checksum(v2)!="d439444a1a9ca9bc8864988e488f720f71b379844b30ddb112bdd8f0ddcfcbbb":
            raise ValueError("V2 identity")
        net=Value()
        net.load_state_dict(torch.load(v2,weights_only=True))
        self.evaluate=Evaluator(net.eval())

    def rank(self,h,history,opening):
        row=self.g2.encoder.encode(h,history)|dict(policy=self.g2.slot,dc_hp=(opening["hp"],h["hp"],opening["max_hp"]))
        scores=next(self.g2.forward([([row],)]))[0][0]
        return sorted(range(len(scores)),key=lambda i:(-float(scores[i]),i))

    def backup(self,results,opening):
        states={};values={};rows=[]
        for r in results:
            mass=sum(x["mass"] for x in r["leaves"])
            if abs(mass+sum(r["gaps"].values())-1)>1e-8:raise ValueError("unaccounted conditional mass")
            for j,leaf in enumerate(r["leaves"]):
                key=(r["index"],j)
                if leaf["kind"]=="C":states[key]=strategic(leaf["facts"],leaf["draw"])
                elif leaf["kind"]=="Victory":
                    values[key]=float(payoff(torch.tensor(opening["hp"]-leaf["hp"]),torch.tensor(opening["max_hp"])))
                elif leaf["kind"]=="Defeat":values[key]=-50.
                else:raise ValueError("terminal/"+leaf["kind"])
            rows.append({k:r[k] for k in ("index","steps","choices","chances","gaps")}|dict(coverage=mass,leaves=len(r["leaves"])))
        values.update(self.evaluate(states,opening))
        for row,r in zip(rows,results):
            row["value"]=sum(x["mass"]*values[r["index"],j] for j,x in enumerate(r["leaves"])) if not r["gaps"] else None
        return rows
