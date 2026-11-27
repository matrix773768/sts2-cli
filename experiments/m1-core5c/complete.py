"""Settle public feedback policies. Every represented draw/selector branches through the reference kernel."""
from collections import Counter
from functools import partial
from panel5c import HOST
from deploy5b import init,host_at,Evaluator,graph_plan,reference
from improve import mass_kind,terminal,digest
from play_loop import step
from policy5c import RULE,can_group,events,move,observation,roots,tactic
from backup5c import combine

class PublicLane:
    def __init__(self,lane):
        self.lane=lane
        self.host=lane.host
    def request(self,command,**kw):
        if command=="i1_core5_reference":
            kw["complete"]=True
        return self.lane.request(command,**kw)

class Turn:
    def __init__(self,lane,h,opening,evaluator,remaining,detail=False):
        self.lane=lane
        self.h=h
        self.opening=opening
        self.evaluator=evaluator
        self.remaining=remaining
        self.detail=detail
        self.cache={}
        self.states={}
        self.values={}
        self.calls=0
        self.cap=0
        self.merges=0
        self.settled=set()
        self.eligible=set()
        self.records=[]
        self.snapshots={}
        self.attempts=0
        self.full=0
    def read(self,route):
        if route not in self.cache:
            if len(self.cache)>=self.cap:
                return "budget",None
            raw=self.lane.request("i1_core5_reference",route=[dict(action=i,draws=t) for i,t in route])["response"]
            self.calls+=raw["calls"]
            k=raw["kind"]
            if k=="decision":
                value=self.lane.host.project(raw["state"])
            elif k=="R":
                value=(raw["support"],raw.get("batch",1))
            else:
                k=mass_kind(raw)
                value=None
                if k in ("C","death","victory"):
                    value=digest(raw["state"])
                    self.states[value]=raw["state"]
                    if k!="C":
                        self.values[value]=terminal(k,raw["state"],self.opening)
            self.cache[route]=k,value
        return self.cache[route]
    def outcomes(self,route,group=False,merged=False,p=1.):
        k,v=self.read(route)
        if k!="R":
            yield p,route,k,v,merged
            return
        support,batch=v
        # Public membership also includes new cards inserted during combat. A generated
        # on-draw listener need never have appeared in the opening deck or the hand.
        clean_draw=all(RULE.get(token.rsplit("#",1)[0],{}).get("HookMask")=="None" for token in support)
        n=batch if group and clean_draw else 1
        if n>1:
            self.merges+=1
        left=1.
        for tape,w in events(support,n):
            i,t=route[-1]
            r=route[:-1]+((i,t+tape),)
            if len(self.cache)>=self.cap and r not in self.cache:
                yield p*left,route,"budget",None,merged
                return
            yield from self.outcomes(r,group,merged or n>1,p*w)
            left-=w
        if abs(left)>1e-9:
            raise ValueError("chance mass")
    def follow(self,h,a,route,style,merged,p,path,rows):
        key=observation(h,merged)
        action=move(h,a)
        path=path+((key,action,merged),)
        if self.detail:
            self.snapshots[key]=h
        route=route+((a["index"],()),)
        if a["kind"]=="end_turn":
            self.eligible.add(route)
        for w,r,k,v,unordered in self.outcomes(route,can_group(h,a),merged,p):
            if k=="decision":
                nxt=tactic(v,style,unordered) if len(path)<min(12,self.remaining) else None
                if nxt is not None:
                    self.follow(v,nxt,r,style,unordered,w,path,rows)
                    continue
                k="action_budget"
            if k in ("C","victory","death") and a["kind"]=="end_turn":
                self.settled.add(route)
            rows.append((w,k,v if isinstance(v,str) else None,path))
    def score(self,rows):
        mass = Counter()
        value = 0.
        for probability, kind, state_key, _ in rows:
            mass[kind] += probability
            value += probability * self.values.get(state_key, -50.)
        coverage = sum(mass[kind] for kind in ("C", "death", "victory"))
        return coverage, value, dict(mass)
    def search(self, admitted=None, quotas=(32,80)):
        plans=[]
        # Reserve a fresh quota for each first action. Cheap complete policies survive later budget cuts.
        for a in (roots(self.h)[:4] if admitted is None else admitted):
            styles=("end","block","repeat","attack")
            by_style={}
            for j,style in enumerate(styles):
                self.cap=len(self.cache)+quotas[int(j!=0)]
                rows=[]
                self.follow(self.h,a,(),style,False,1.,(),rows)
                if abs(sum(x[0] for x in rows)-1)>1e-8:
                    raise ValueError("proposal mass")
                by_style[style]=rows
            self.values.update(self.evaluator({k:c for k,c in self.states.items() if k not in self.values},self.opening))
            scored = [(self.score(rows), rows) for rows in by_style.values()]
            full = [rows for (coverage, _, _), rows in scored if coverage >= 1-1e-9]
            self.attempts += len(scored)
            self.full += len(full)
            if full:
                chosen = combine(full, self.score)
            else:
                _, chosen = max(scored, key=lambda result: (round(result[0][0], 10), result[0][1]))
            if self.detail:
                self.records.append(dict(first=move(self.h,a),proposals=by_style,chosen=chosen))
            plans.append((self.score(chosen),chosen))
        return max(plans,key=lambda z:(round(z[0][0],9),z[0][1])) if plans else None

def program(rows):
    table={}
    for _,_,_,path in rows:
        prefix=()
        for key,action,merged in path:
            entry=(prefix,key)
            if table.setdefault(entry,action)!=action:
                raise ValueError("ambiguous policy")
            prefix=prefix+((key,action),)
    return table
def execute_program(lane,st,table):
    history=[]
    prefix=()
    while st["status"]=="active" and st["actions"]<128:
        h=lane.host.project(st["observation"])
        matches=[]
        for merged in (False,True):
            key=observation(h,merged)
            if (prefix,key) in table:
                matches.append((key,table[prefix,key]))
        if len(set(matches))!=1:
            raise ValueError("Compiled policy has no unique public observation")
        key,action=matches[0]
        a=next((a for a in h["actions"] if move(h,a)==action),None)
        if a is None:
            raise ValueError("Compiled action missing from the live legal menu")
        idx=a["index"]
        history.append((h,idx))
        st=step(lane,st,idx)
        if a["kind"]=="end_turn":
            return st,history,"end"
        prefix+=((key,action),)
    return st,history,"terminal" if st["status"]!="active" else "action_budget"

class Planner:
    def __init__(self,net,reference_only=False):
        self.evaluator=Evaluator(net)
        self.detail=False
        self.last=None
        self.reference_only=reference_only
        self.inspect=None
        self.graph_budget=(512,80,256,20)
        self.quotas=(32,80)
        self.admit=None
    def __call__(self,lane,h,past,net,g2,opening):
        public=PublicLane(lane)
        try:
            transitions,settle,ref,expansions=self.graph_budget
            g,ch,q=graph_plan(public,h,past,net,g2,opening,settle,direct=partial(reference,limit=ref),
                fast=True,evaluator=self.evaluator,transitions=transitions,expansions=expansions,inspect=self.inspect)
            if self.reference_only:
                return g,ch,q
            turn=Turn(public,h,opening,self.evaluator,128-len(past),self.detail)
            best=turn.search(self.admit(h) if self.admit else None,self.quotas)
            if self.detail:
                self.last=turn
            q.update(policy_requests=len(turn.cache),policy_calls=turn.calls,policy_ends=len(turn.eligible),
                     settled_ends=len(turn.settled),grouped=turn.merges,conditional=False,
                     full_policies=turn.full,attempted_policies=turn.attempts)
            q["calls"]+=turn.calls
            if best:
                (cov,value,mass),rows=best
                if (round(cov,9),value)>(round(q["coverage"],9),q["value"]):
                    q.update(coverage=cov,value=value,candidate_mass=mass,conditional=True,
                        use=cov>=1-1e-9 and q["reference_coverage"]>=1-1e-9 and value>q["reference"]+1)
                    if q["use"]:
                        g={"execute":partial(execute_program,table=program(rows))}
                        ch={0:0}
            return g,ch,q
        finally:
            lane.request("i1_core5_reference",clear=True)
def setup(out,arm):
    old,g2,net,_=init(out,"V1high" if arm=="V1complete" else "high")
    old.close()
    return host_at(out,HOST),g2,net,Planner(net,reference_only=arm=="referenceOnly")
