"""Shared typed event encoder. Rule keys never enter numeric tensors."""
from core4_roots import *
from state import static_rules
from functools import lru_cache
from collections import Counter,deque
import math
import numpy as np
from torch import nn
import torch
from value import CENTERS,expected,targets,payoff

fields="""enemy node edge hit effect power relic card layer setup hp maxhp block energy stars damage actual hits amount order depth branch back cycle cooldown allowed repeat_limit repeat_once repeat_block conditional threshold growth strength dexterity weak vulnerable draw gainblock heal losehp exhaust generate apply_self apply_target aoe random attack skill persistent status hand discard spent bag deck top bottom position count cost star_cost until_turn until_play permanent reduce_only absolute upgrade before after trigger_card trigger_turn trigger_damage trigger_block trigger_draw trigger_exhaust target_self target_enemy unknown living phase_index history_length register expire has_cost base_magic multiplicity""".split()
F={k:i for i,k in enumerate(fields)}
with gzip.open(HERE/"cards.json.gz","rt") as f:CARDS=json.load(f)
OPS={"Attack":"attack","AttackAll":"aoe","AttackRandom":"random","Draw":"draw","GainBlock":"gainblock","Heal":"heal","LoseHp":"losehp","AddFixedCard":"generate","ApplyPowerSelf":"apply_self","ApplyPowerTarget":"apply_target","ApplyPowerAllEnemies":"aoe"}
PV={"STRENGTH_POWER":"strength","DEXTERITY_POWER":"dexterity","WEAK_POWER":"weak","VULNERABLE_POWER":"vulnerable","DEMON_FORM_POWER":"growth","RITUAL_POWER":"growth"}
def tensor_row(**v):
    row=np.zeros(len(F),np.float32)
    for k,n in v.items():
        if n is not None:row[F[k]]=math.copysign(math.log1p(abs(float(n))),float(n))
    return row

def hooks(rule):
    h=rule.get("HookMask","")
    return {k:1 for k,v in (("before","Before"),("after","After"),("trigger_card","CardPlayed"),("trigger_turn","Turn"),("trigger_damage","Damage"),("trigger_block","Block"),("trigger_draw","Draw"),("trigger_exhaust","Exhaust")) if v in h}

def encode(c):
    if c["setup"]["stage"]!="before_initial_draw" or c.get("enemy_models"):
        raise ValueError("A strict post-enemy, pre-draw C is required")
    tokens=[];rules=static_rules()
    def add(attrs,**extra):tokens.append(tensor_row(**(attrs|extra)))
    def powers(items,owner):
        for p in items:
            key=p["id"];amount=p["amount"];r=rules["powers"].get(key,{})
            add(owner|hooks(r),power=1,amount=amount,**{PV.get(key,"unknown"):amount})
    powers(c["powers"],{})
    for r in c["relics"]:add(hooks(rules["relics"].get(r["id"],{})),relic=1,count=r.get("counter"),trigger_card=int(r["id"] in ("NUNCHAKU","TUNING_FORK")),energy=int(r["id"]=="NUNCHAKU"),gainblock=int(r["id"]=="TUNING_FORK"))
    for e in c["enemies"]:
        owner=dict(enemy=1,hp=e["hp"],maxhp=e["max_hp"],block=e["block"])
        add(owner,living=int(e["hp"]>0));powers(e["powers"],owner)
        if not e["hp"]:continue
        ph=e.get("phase") or {};history=ph.get("committed_moves",[])
        graph={n["MoveId"]:n for n in rules["graphs"].get(e["species"],[])}
        queue=deque([(e.get("move"),0,())]);expanded=set()
        for i,h in enumerate(e["attack_hits"]):add(owner,hit=1,actual=h,order=i+1,hits=len(e["attack_hits"]))
        for key,v in ph.get("registers",{}).items():
            add(owner,register=1,amount=v,**({"generate":1} if "curse" in key else {"heal":1} if "respawn" in key else {"conditional":1}))
        while queue:
            key,depth,path=queue.popleft()
            if key in expanded or depth>5:continue
            expanded.add(key);n=graph.get(key,{})
            role=owner|dict(depth=depth,phase_index=int(depth==0),history_length=history.count(key))
            add(role,node=1,damage=n.get("BaseDamage"),hits=n.get("Repeats"),unknown=int(not n))
            for i,a in enumerate(n.get("attacks",[])):add(role,hit=1,order=i+1,damage=a["BaseDamage"],hits=a["Repeats"])
            for i,ef in enumerate(n.get("effects",[])):
                add(role,effect=1,order=i+1,amount=ef["Amount"],**{OPS.get(ef["Op"],"unknown"):1,PV.get(ef.get("power"),"unknown"):ef["Amount"]})
            cond=n.get("condition") or {};predicate=cond.get("predicate","")
            ws={w["target"]:w for w in ph.get("repeat_windows",{}).get(key,[])}
            for child in n.get("targets",[])+([n["next"]] if n.get("next") else []):
                w=ws.get(child,{});dest=graph.get(child,{})
                add(role,edge=1,cycle=int(child in path+(key,)),branch=len(n.get("targets",[])),conditional=int(bool(cond)),
                    threshold=.5 if "half" in predicate else 2 if "lt_2" in predicate else 0,
                    register=int("register" in predicate),back=int(cond.get("whenFalse")==child),damage=dest.get("BaseDamage"),
                    hits=dest.get("Repeats"),allowed=int(w.get("allowed_by_history",True)),cooldown=w.get("cooldown"),
                    repeat_once=int(w.get("repeat")=="UseOnlyOnce"),repeat_block=int(w.get("repeat")=="CannotRepeat"),repeat_limit=w.get("max_times"))
                queue.append((child,depth+1,path+(key,)))
    def card(name,zone,num=1,pos=0,instance=None):
        key,_,up=name.rpartition("#");r=CARDS.get(key,{});u=int(up);prefix="Upgraded" if u else "Base"
        attr={zone:1,"card":1,"multiplicity":num,"position":pos,"upgrade":u,"unknown":int(not r),
              "cost":(instance or {}).get("cost",r.get(prefix+"Cost")),"damage":r.get(prefix+"Damage"),"block":r.get(prefix+"Block"),
              "hits":r.get(prefix+"Hits"),"base_magic":r.get(prefix+"Magic")}
        attr[{"Power":"persistent","Attack":"attack","Skill":"skill"}.get(r.get("Type"),"status")]=1
        attr["target_self" if r.get("Target")=="Self" else "target_enemy"]=1
        for op in r.get("operations",[]):attr[OPS.get(op["Op"],"unknown")]=1
        vals=dict(zip(r.get("OrderedVarNames",[]),r.get(prefix+"VarValues",[])))|(instance or {}).get("vars",{})
        for k,v in vals.items():
            mapped={"Damage":"damage","Block":"block","Cards":"draw","Energy":"energy","StrengthPower":"strength","VulnerablePower":"vulnerable","DexterityPower":"dexterity"}.get(k)
            if mapped:attr[mapped]=v
        add(attr)
        for resource,layers in (instance or {}).get("cost_layers",{}).items():
            for i,l in enumerate(layers):
                ex=l.get("expires","")
                add(attr,layer=1,order=i+1,amount=l.get("amount",l.get("cost")),star_cost=int(resource=="stars"),
                    permanent=int("Combat" in ex),until_turn=int("Turn" in ex or l.get("clears_when_turn_ends",False)),
                    until_play=int("Played" in ex or l.get("clears_when_card_is_played",False)),reduce_only=l.get("reduce_only",False))
    for z,cs in c["card_state"].items():
        for i,inst in enumerate(cs):card(inst["type"],"spent" if z=="exhaust" else z,pos=i+1 if z=="hand" else 0,instance=inst)
    for k,n in Counter(d["id"]+"#"+str(d["upgrade"])for d in c["deck"]).items():card(k,"deck",n)
    law=c["belief"]
    for k,n in law["counts"].items():card(k,"bag",n)
    for z in ("top","bottom"):
        for i,k in enumerate(law[z]):card(k,z,pos=i+1)
    s=c["setup"];add({},setup=1,draw=s["draw"],generate=int(s["will_shuffle"]),count=len(s["pending"]),unknown=int(bool(law.get("order_gap") or law.get("membership_gap"))))
    foes=[e for e in c["enemies"] if e["hp"]>0]
    glob=[c["hp"],c["max_hp"],c["hp"]/c["max_hp"],c["turn"],sum(e["hp"] for e in foes),sum(sum(e["attack_hits"])for e in foes),
        len(foes),c["energy"],c["block"],c["stars"],c["draw_count"],len(c["deck"]),len(c["exhaust"]),len(c["hand"]),len(c["discard"]),s["draw"]]
    return np.log1p(glob).astype(np.float32),np.stack(tokens)

def pack(rows):
    n=max(len(t)for _,t in rows);x=np.zeros((len(rows),n,len(F)),np.float32);mask=np.zeros((len(rows),n),bool)
    for i,(_,t) in enumerate(rows):x[i,:len(t)]=t;mask[i,:len(t)]=True
    return torch.from_numpy(np.stack([g for g,_ in rows])),torch.from_numpy(x),torch.from_numpy(mask)

class Value(nn.Module):
    def __init__(self):
        super().__init__()
        self.entity=nn.Sequential(nn.Linear(len(F),48),nn.SiLU(),nn.Linear(48,32),nn.SiLU())
        self.attention=nn.Linear(32,4)
        self.head=nn.Sequential(nn.Linear(16+32*5,96),nn.LayerNorm(96),nn.SiLU(),nn.Dropout(.1),nn.Linear(96,1+len(CENTERS)))
    def forward(self,g,x,m):
        v=self.entity(x);w=self.attention(v).masked_fill(~m.unsqueeze(-1),-1e6).softmax(1)
        pool=torch.bmm(w.transpose(1,2),v).flatten(1)
        return self.head(torch.cat((g,pool,(v*m.unsqueeze(-1)).sum(1)/m.sum(1,keepdim=True).sqrt()),1))
