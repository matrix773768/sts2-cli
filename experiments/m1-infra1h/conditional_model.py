"""Compile frozen tactic decisions and value backup over resident, ordered DFS outcomes."""
from collections import Counter
import json

metrics=Counter()

def save(folder):
    (folder/"infra1h-policy-reuse.json").write_text(json.dumps(metrics))

def install(memo=False):
    import complete
    from policy5c import move,observation,tactic,can_group

    base=complete.Turn
    class ResidentTurn(base):
        def search(self,*args,**kwargs):
            # Diagnostics can inspect the original Python cache and full click-through snapshots.
            self.resident=not self.detail
            if self.resident:
                self.first_request=True
                self.materialized={}
                self.direct={}
                self.bindings={}
                self.tactics={}
            return super().search(*args,**kwargs)

        def follow(self,h,a,route,style,merged,p,path,rows):
            if not getattr(self,"resident",False):
                return super().follow(h,a,route,style,merged,p,path,rows)
            slot=a["index"]
            binding=(id(h),slot,merged)
            if memo and binding in self.bindings:
                edge=self.bindings[binding]
            else:
                edge=(observation(h,merged),move(h,a),merged)
                if memo:self.bindings[binding]=edge
            path=path+(edge,)
            request=dict(parent=route or 0,action=a["index"],group=can_group(h,a),merged=merged,
                         p=p,cap=self.cap,reset=self.first_request)
            self.first_request=False
            lookup=(route or 0,slot)
            direct_id=self.direct.get(lookup) if memo else None
            is_end=a["kind"]=="end_turn"
            base_id=None
            while True:
                if direct_id is not None:
                    # A cached base response was a single non-chance result. The resident
                    # Read would return it without touching size, budget, or prefix order.
                    packet=dict(base_id=direct_id,rows=[dict(id=direct_id,p=p,merged=merged)],
                                cursor=0,size=len(self.cache),calls=self.calls,merges=self.merges)
                    metrics["local_responses"]+=1
                else:
                    packet=self.lane.request("i1_infra1h_conditional",**request)
                    if memo:
                        metrics["host_packets"]+=1
                        items=packet["rows"]
                        if base_id is None and not packet["cursor"] and len(items)==1 and items[0]["id"]==packet["base_id"]:
                            self.direct[lookup]=packet["base_id"]
                if base_id is None:
                    base_id=packet["base_id"]
                    if is_end:self.eligible.add(base_id)
                self.calls=packet["calls"]
                self.merges=packet["merges"]
                # CORE search uses only len(cache) for the next style quota. The
                # actual map of all route identities and responses lives in C#.
                self.cache=range(packet["size"])
                for item in packet["rows"]:
                    idx=item["id"];weight=float(item["p"]);unordered=item["merged"]
                    if idx<0:kind,value="budget",None
                    elif idx in self.materialized:kind,value=self.materialized[idx]
                    else:
                        raw=item["raw"]
                        if raw["kind"]=="decision":kind,value="decision",self.lane.host.project(raw["state"])
                        else:
                            kind=complete.mass_kind(raw);value=None
                            if kind in ("C","death","victory"):
                                value=complete.digest(raw["state"])
                                self.states[value]=raw["state"]
                                if kind!="C":self.values[value]=complete.terminal(kind,raw["state"],self.opening)
                        self.materialized[idx]=kind,value
                    if kind=="decision":
                        nxt=None
                        if len(path)<min(12,self.remaining):
                            tkey=(idx,style,unordered)
                            if memo and tkey in self.tactics:nxt=self.tactics[tkey]
                            else:
                                nxt=tactic(value,style,unordered)
                                if memo:self.tactics[tkey]=nxt
                        if nxt is not None:
                            self.follow(value,nxt,idx,style,unordered,weight,path,rows)
                            continue
                        kind="action_budget"
                    if is_end and kind in ("C","death","victory"):self.settled.add(base_id)
                    rows.append((weight,kind,value if isinstance(value,str) else None,path))
                if not packet["cursor"]:return
                request=dict(cursor=packet["cursor"])
    complete.Turn=ResidentTurn
