"""Midcombat audit lane for the 5E Corpse Slugs turn. Uses public C history and current B."""
from collections import Counter
from lane import BranchLane,Unsupported,stripped
from copy import deepcopy
class SlugLane(BranchLane):
    def __init__(self,lane,public):
        self.lane=lane;self.host=lane.host
        self.root=public["wire"];self.prior=public["prior"];self.bag_order=list(public["law"]["counts"])
        self.cache={};self.prefixes={};self.pending={}
        self.stage="slug123";self.physical=Counter()
        r=self.rpc("open_slugs",**public)
        self.node=r["node"];self.facts={self.node:r["facts"]}
        self.opened=self.public_b(r["facts"])
        if self.opened!=self.root:
            from check import delta
            raise Unsupported("slugs/opening/"+str(delta(self.opened,self.root)[:3]))
    def public_b(self,f):
        foes=f["foes"]
        if any(not e["alive"] for e in foes):raise Unsupported("slugs/changed_roster")
        powers=f["powers"]
        if any(p["id"] not in ("FRAIL_POWER","RAVENOUS_POWER","NO_DRAW_POWER") for p in powers):raise Unsupported("slugs/preview_hook")
        player=[dict(id=p["id"],amount=p["amount"]) for p in powers if p["owner"]==0 and p["id"]=="FRAIL_POWER"]
        h={k:deepcopy(self.root[k]) for k in ("schema","potions","relics","deck")}
        h.update({k:f[k] for k in ("turn","hp","max_hp","block","energy","stars","draw_count")})
        h.update(hand=stripped(f["hand"],True),discard=stripped(f["discard"]),exhaust=stripped(f["exhaust"],sort=True),
            powers=player,allies=[dict(index=0,hp=f["hp"],block=f["block"],attack_hits=[],intents=[],powers=player)],
            decision={"phase":"combat"},enemies=[dict(index=i,hp=e["hp"],block=e["block"],attack_hits=self.root["enemies"][i]["attack_hits"],
                intents=self.root["enemies"][i]["intents"],powers=[]) for i,e in enumerate(foes)])
        h["order_hooks"]=sorted([dict(owner=p["owner"]-3 if p["owner"] else -1,id=p["id"]) for p in powers],key=lambda x:(x["owner"],x["id"]))
        h["mechanism"]=dict(played=f["played"],attacks=f["attacks"],skills=f["skills"],stacks=[dict(owner=-1,id=p["id"],amount=p["amount"]) for p in powers if p["id"]=="NO_DRAW_POWER"],species=["CORPSE_SLUG"]*len(foes))
        h["actions"]=[]
        for a in self.actions(f,{}):
            if any(p["id"]=="FRAIL_POWER" for p in player) and "block" in a.get("preview",{}):
                a["preview"]["block"]=a["preview"]["block"]*3//4
            for i in range(len(foes)) if a.get("target_side")=="enemy" else [None]:
                h["actions"].append(a|dict(index=len(h["actions"]))|({"target":i} if i is not None else {}))
        return h
    def public_c(self,f,draw):
        if f["turn"]!=3 or f["round"]!=3:raise Unsupported("slugs/C_timer")
        if any(p["id"] not in ("FRAIL_POWER","RAVENOUS_POWER","NO_DRAW_POWER") for p in f["powers"]):raise Unsupported("slugs/C_power")
        def powers(owner):
            return [dict(id=p["id"],amount=p["amount"]) for p in f["powers"] if p["owner"]==owner]
        c=self.strategic_base(f,draw,powers(0));c["enemies"]=[]
        for e,prior in zip(f["foes"],self.prior["enemies"],strict=True):
            if not e["alive"]:raise Unsupported("slugs/C_dead_slot")
            c["enemies"].append(dict(slot=e["slot"],species="CORPSE_SLUG",hp=e["hp"],max_hp=e["max_hp"],block=e["block"],
                move=e["move"],attack_hits=e["attack_hits"],powers=powers(e["slot"]+3),phase=dict(node=e["move"],
                repeat_windows={},registers={},rule_ref="CORPSE_SLUG",committed_moves=prior["phase"]["committed_moves"]+[e["move"]])))
        return c
