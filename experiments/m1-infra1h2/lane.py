"""Public state adapter. A turn owns its stable Hot parents and releases them together."""
from collections import Counter
from copy import deepcopy
from wire import embedded,card as embedded_card

class Unsupported(Exception):
    pass

def token(c):
    return f"{c['id']}#{c['upgrade']}"

def stripped(rows, cost=False, sort=False):
    if sort:
        rows=sorted(rows,key=lambda c:(c["id"],c["upgrade"]))
    return [dict(index=i,id=c["id"],upgrade=c["upgrade"])|({"cost":c["cost"]} if cost else {})
            for i,c in enumerate(rows)]

class BranchLane:
    def __init__(self,lane,wire,spec,*,law=None,audit_uid_base=None):
        self.lane=lane
        self.host=lane.host
        self.root=wire
        self.cache={}
        self.physical=Counter()
        self.stage="conditional"
        counts=Counter(map(token,wire["deck"]))
        counts.subtract(map(token,wire["hand"]))
        if min(counts.values(),default=0)<0 or sum(counts.values())!=wire["draw_count"]:
            raise Unsupported("opening/nonexchangeable")
        # CORE seeds its count dictionary from the public constructed deck, then
        # subtracts visible cards. Its frozen tensor encoder iterates that dictionary.
        initial=Counter(map(token,spec["deck"]));initial.subtract(map(token,wire["hand"]))
        self.bag_order=list(law["counts"] if law is not None else +initial)
        if set(self.bag_order)!=set(+counts):raise Unsupported("opening/public_bag_order")
        r=self.rpc("open",wire=wire,ascension=spec["ascension"],gold=spec.get("gold",99),counts=+counts,**({} if audit_uid_base is None else {"audit_uid_base":audit_uid_base}))
        self.node=r["node"]
        self.facts={self.node:r["facts"]}
        self.prefixes={}
        self.pending={}
        self.opened=self.public_b(r["facts"])
        if self.opened!=wire:
            raise Unsupported("opening/wire/"+",".join(k for k in wire.keys()|self.opened.keys() if wire.get(k)!=self.opened.get(k)))

    def rpc(self,op,**kw):
        self.physical[op]+=1
        r=self.lane.request("i1_h2_branch",op=op,**kw)["result"]
        if op=="advance":self.physical[self.stage+"/"+r["kind"]]+=1
        if r.get("kind")=="unsupported":raise Unsupported(r["reason"])
        return r

    def public_b(self,f):
        # Nonprojected arrays are reconstructed even for G2. Public immutable fields
        # come from the current opening. Only the qualified monster's intent stays
        # fixed during this player phase.
        h={k:deepcopy(self.root[k]) for k in ("schema","potions","relics","deck")}
        root_enemy=self.root["enemies"][0]
        permitted={"ARTIFACT_POWER","NO_DRAW_POWER","DEMON_FORM_POWER","DARK_EMBRACE_POWER","STRENGTH_POWER","DEXTERITY_POWER"}
        if any(p["id"] not in permitted or (p["owner"]==3 and p["id"]!="ARTIFACT_POWER") for p in f["powers"]):
            raise Unsupported("B/power/"+str(f["powers"]))
        amounts={p["id"]:p["amount"] for p in f["powers"] if p["owner"]==0}
        shown=sorted([dict(id=k,amount=v) for k,v in amounts.items() if k in ("STRENGTH_POWER","DEXTERITY_POWER")],key=lambda x:x["id"])
        h.update({k:f[k] for k in ("turn","hp","max_hp","block","energy","stars","draw_count")})
        h.update(hand=stripped(f["hand"],True),discard=stripped(f["discard"]),exhaust=stripped(f["exhaust"],sort=True),
                 powers=shown,decision={"phase":"combat"})
        h["allies"]=[dict(index=0,hp=f["hp"],block=f["block"],attack_hits=[],intents=[],powers=shown)]
        h["enemies"]=[dict(index=0,hp=f["enemy_hp"],block=f["enemy_block"],attack_hits=root_enemy["attack_hits"],
                            intents=root_enemy["intents"],powers=[])]
        h["order_hooks"]=sorted([dict(owner=0 if p["owner"]==3 else -1,id=p["id"]) for p in f["powers"]],key=lambda x:(x["owner"],x["id"]))
        h["mechanism"]=dict(played=f["played"],skills=f["skills"],attacks=f["attacks"],species=["MECHA_KNIGHT"],
                            stacks=sorted([dict(owner=0 if p["owner"]==3 else -1,id=p["id"],amount=p["amount"]) for p in f["powers"] if p["id"] not in ("STRENGTH_POWER","DEXTERITY_POWER")],key=lambda x:(x["owner"],x["id"])))
        h["actions"]=self.actions(f,amounts)
        return h

    def actions(self,f,amounts):
        actions=[]
        for binding in f["actions"]:
            j=binding["slot"];c=f["hand"][j];t=binding["target"];name=c["id"]
            if t not in ("AnyEnemy","Self","None","AllEnemies","RandomEnemy"):raise Unsupported("B/target/"+t)
            if c["cost"]<0:raise Unsupported("B/X_cost")
            a=dict(index=len(actions),kind="play_card",card=j,cost=c["cost"],star_cost=max(0,binding["stars"]),
                   energy_x=c.get("energy_x",name=="WHIRLWIND"),star_x=False,target_type=t)
            if t=="AnyEnemy":a.update(target=0,target_side="enemy")
            preview={}
            if name in ("STRIKE_IRONCLAD","BASH","TWIN_STRIKE","POMMEL_STRIKE"):
                preview.update(damage_per_hit=max(0,binding["damage"]+amounts.get("STRENGTH_POWER",0)),hits=2 if name=="TWIN_STRIKE" else 1)
            if name in ("DEFEND_IRONCLAD","SHRUG_IT_OFF","FLAME_BARRIER"):
                preview["block"]=max(0,binding["block"]+amounts.get("DEXTERITY_POWER",0))
            if name in ("SHRUG_IT_OFF","POMMEL_STRIKE"):preview["draw"]=c["vars"]["Cards"]
            if preview:a["preview"]=preview
            actions.append(a)
        return actions+[dict(index=len(actions),kind="end_turn",energy_x=False,star_x=False)]

    def public_c(self,f,draw):
        if f["move"]!="FLAMETHROWER_MOVE" or f["round"]!=2:raise Unsupported(f"C/monster_phase/{f['move']}/{f['round']}")
        if any(p["id"] not in ("ARTIFACT_POWER","VULNERABLE_POWER","STRENGTH_POWER","NO_DRAW_POWER") for p in f["powers"]):
            raise Unsupported("C/power_visibility")
        def powers(owner):
            return sorted([dict(id=p["id"],amount=p["amount"]) for p in f["powers"] if p["owner"]==owner],key=lambda p:p["id"])
        if any(p["id"]!="ARTIFACT_POWER" for p in f["powers"] if p["owner"]==3):
            raise Unsupported("C/intent_modifiers")
        c=self.strategic_base(f,draw,powers(0))
        c["enemies"]=[dict(slot=0,species="MECHA_KNIGHT",hp=f["enemy_hp"],max_hp=f["enemy_max_hp"],block=f["enemy_block"],
                         move=f["move"],attack_hits=f["attack_hits"],powers=powers(3),
                         phase=dict(node=f["move"],repeat_windows={},registers={},rule_ref="MECHA_KNIGHT",
                                    committed_moves=["CHARGE_MOVE",f["move"]]))]
        return c

    def strategic_base(self,f,draw,player_powers):
        c={k:f[k] for k in ("turn","round","hp","max_hp","block","energy","stars","gold","draw_count")}
        c.update(schema="sts2.core.c.v3",deck=self.root["deck"],relics=[],potions=self.root["potions"],powers=player_powers,
                 belief={k:f[k] for k in ("counts","top","bottom","shuffles")},events=[],enemy_models=[])
        if f["shuffles"] or any(k not in self.bag_order for k in f["counts"]):
            raise Unsupported("C/changed_public_bag_order")
        c["belief"]["counts"]={k:f["counts"][k] for k in self.bag_order if k in f["counts"]}
        c["card_state"]={}
        for zone in ("hand","discard","exhaust"):
            rows=f[zone] if zone=="hand" else sorted(f[zone],key=token)
            c[zone]=stripped(rows,cost=zone=="hand",sort=zone!="hand")
            c["card_state"][zone]=[dict(type=token(r),cost=r["cost"],vars=r["vars"],cost_layers={"energy":[],"stars":[]}) for r in rows]
        c["setup"]=dict(stage="before_initial_draw",draw=draw,will_shuffle=f["draw_count"]<draw,side_started=False,
                       extra_turn=False,completed=["enemy_side","before_hand_draw","modified_draw_count"],
                       pending=["hand_draw","draw_hooks","after_player_start","side_start","deaths_orbs_autoplay"])
        return c

    def request(self,command,**kw):
        if command=="i1_infra1_reference_batch":
            return {"results":[self.request("i1_core5_reference",**request)["response"] for request in kw["requests"]]}
        if command=="i1_core1r2":
            from tactics import tactical
            before=self.stage;self.stage=kw.get("mode","graph")
            try:return tactical(self,**kw)
            finally:self.stage=before
        if command!="i1_core5_reference":raise Unsupported("path/"+command)
        if kw.get("clear"):
            self.prefixes.clear()
            return {"response":{"kind":"cleared"}}
        route=kw["route"]
        keys=[];key=()
        for edge in route:
            key+=((edge["action"],tuple(edge.get("draws",[]))),);keys.append(key)
        calls=len(keys)-max((i for i,k in enumerate(keys,1) if (kw.get("complete",False),k) in self.prefixes),default=0)
        node=self.node;wire=self.opened;previous=()
        for key in keys:
            index,inputs=key[-1]
            if key in self.cache:
                node,wire,r=self.cache[key];previous=key
                continue
            a=wire["actions"][index]
            kind=a["kind"]
            if kind=="select_candidate":
                origin,slot,target,prior,options=self.pending[previous]
                self.pending[key]=origin,slot,target,prior,options
                wire=deepcopy(wire)
                wire["decision"]["selected"]=[a["choice"]]
                wire["actions"]=[dict(index=0,kind="confirm_selection",energy_x=False,star_x=False)]
                wire=embedded(wire)
                r=dict(kind="decision",state=wire)
            else:
                if kind=="confirm_selection":
                    node,slot,target,prior,options=self.pending[previous]
                    inputs=prior+(options[wire["decision"]["selected"][0]]["uid"],)+inputs
                else:
                    slot=a.get("card",-1);target=a.get("target",-1)
                r=self.rpc("advance",parent=node,slot=slot,target=target,inputs=inputs)
                boundary=r["kind"]
                if boundary=="decision":
                    node=r["node"];self.facts[node]=r["facts"];wire=self.public_b(r["facts"])
                    r=dict(kind=boundary,state=wire)
                elif boundary=="C":r=dict(kind=boundary,state=self.public_c(r["facts"],r["draw"]))
                elif boundary=="choice":
                    options=r["options"]
                    source=self.facts[node]["hand"][slot]["id"]
                    if source not in ("BURNING_PACT","HEADBUTT"):raise Unsupported("selector/"+source)
                    zone="hand" if source=="BURNING_PACT" else "discard"
                    facts=r["facts"]
                    lookup={c["uid"]:c for c in facts[zone]}
                    if any(o["uid"] not in lookup for o in options):raise Unsupported("selector/instance_binding")
                    candidates=stripped([lookup[o["uid"]] for o in options])
                    view=self.public_b(facts)
                    for k in ("played","attacks","skills"):view["mechanism"][k]=wire["mechanism"][k]
                    view["decision"]=dict(phase="choice",effect="Exhaust" if zone=="hand" else "MoveToDrawTop",
                        pile=zone.capitalize(),timing="Action",min=1,max=1,candidates=list(map(embedded_card,candidates)),selected=[])
                    view["actions"]=[dict(index=i,kind="select_candidate",choice=i,energy_x=False,star_x=False) for i in range(len(options))]
                    self.pending[key]=node,slot,target,inputs,options
                    wire=embedded(view);r=dict(kind="decision",state=wire)
                elif boundary in ("victory","death"):r=dict(kind=boundary,state=r["state"])
                elif boundary!="R":raise Unsupported("response/"+boundary)
            self.cache[key]=(node,wire,r)
            previous=key
        if r["kind"]=="decision" and wire["decision"]["phase"]=="combat" and calls:
            new_key=(kw.get("complete",False),key)
            if len(self.prefixes)>=48:
                # Dictionary.Remove + Add in the frozen .NET host reuses its
                # first enumerated slot. The other 47 slots keep their positions.
                first=next(iter(self.prefixes));del self.prefixes[first]
                self.prefixes={new_key:None,**self.prefixes}
            else:self.prefixes[new_key]=None
        return {"response":r|dict(calls=calls)}

    def close(self):
        self.rpc("clear")
