"""Trace fixed turn proposals through public branching and score each realized C under both frozen weights."""
import gzip,json
from collections import Counter
from functools import lru_cache
from time import perf_counter
from pathlib import Path

from review import E,FIVE,LOGS,ROOT,Search,Lane,init,load_net,Evaluator,fight,description,host_at
from play_loop import cohort,step
from improve import digest,terminal,mass_kind
from turn_lines import *

def source(tag):
    with gzip.open(E/f"review-{tag}.gz") as f:return json.load(f)

def prefix(lane,model,net,d):
    trace=[];r=fight(lane,model,d["spec"],"high",net,planner=Search(net,"high"),trace=trace)
    assert r["terminal"]==d["right"]["row"]["terminal"]
    lane.reset()
    return [(h,i) for h,i in trace if h["turn"]<d["turn"]]

def restore(lane,d,past):
    st=cohort.start(lane,d["spec"])
    for expected,i in past:
        assert lane.host.project(st["observation"])==expected
        st=step(lane,st,i)
    assert lane.host.project(st["observation"])==d["right"]["snapshot"]["h"]
    return st

class Tree:
    def __init__(self,lane,d,nets):
        self.lane=lane;self.d=d;self.nets=nets;self.states={};self.scores={}
        self.h=d["right"]["snapshot"]["h"];self.rpc=0
        self.read=lru_cache(maxsize=9000)(self._read)
    def _read(self,route):
        r=self.lane.request("i1_core5_reference",route=[dict(action=i,draws=list(tape)) for i,tape in route])["response"]
        self.rpc+=1;k=r["kind"]
        if k=="decision":return k,self.lane.host.project(r["state"])
        if k=="R":return k,r["support"]
        k=mass_kind(r)
        if k in ("C","victory","death"):
            key=digest(r["state"]);self.states[key]=r["state"]
            if k!="C":self.scores[key]=[terminal(k,r["state"],self.d["spec"])]*2
            return "leaf",key
        return "leaf","?"+k
    def expand(self,route,p=1.):
        k,x=self.read(route)
        if k!="R":
            yield route,p,k,x;return
        i,tape=route[-1];total=sum(x.values())
        for event,n in x.items():
            yield from self.expand(route[:-1]+((i,tape+(event,)),),p*n/total)
    def walk(self,h,route,remaining,witness=None,path=(),mass=1.):
        move,after=select(h,remaining)
        idx=choices(h).get(move)
        if idx is None:return {"?illegal":1.}
        dist=Counter()
        for r,p,k,x in self.expand(route+((idx,()),)):
            record=path+((move,r[-1][1]),) if witness is not None else ()
            if k=="leaf":
                dist[x]+=p
                if witness is not None:witness.append(dict(actions=record,p=mass*p,leaf=x))
            else:
                for key,w in self.walk(x,r,after,witness,record,mass*p).items():dist[key]+=p*w
        return dict(dist)
    def score(self,dist):
        cs={key:self.states[key] for key in dist if key not in self.scores and not key.startswith("?")}
        if cs:
            vals=[net(cs,self.d["spec"]) for net in self.nets]
            self.scores.update({k:[v[k] for v in vals] for k in cs})
        return [sum(w*self.scores.get(k,[-50,-50])[i] for k,w in dist.items()) for i in (0,1)]
    def reset_cache(self):
        self.lane.request("i1_core5_reference",clear=True);self.read.cache_clear()

def coverage(dist):return sum(w for k,w in dist.items() if not k.startswith("?"))
def measure(tag):
    started=perf_counter();d=source(tag);out=LOGS/f"turn-probe-{tag}";out.mkdir(exist_ok=True)
    host,g2,v2,_=init(out,"high");lane=Lane(host,0)
    nets=[Evaluator(load_net(FIVE.parent/"m1-core4/evidence/v1.pt","V1high")),Evaluator(v2)]
    past=prefix(lane,g2,v2,d);st=restore(lane,d,past)
    tree=Tree(lane,d,nets);h=tree.h
    fixed={"deployed":(BASH,SHRUG),"defend2":(SHRUG,DEF,DEF),"shrug_bash":(SHRUG,BASH)} if tag=="rescue" else {"deployed":(BARRIER,WAVE),"head_combo":(HEAD,TRANCE,IMP),"trance_static":(TRANCE,BARRIER,WAVE)}
    lines={}
    for name,moves in fixed.items():
        witness=[]
        dist=tree.walk(h,(),moves,witness);lines[name]=dict(moves=moves,dist=dist,v=tree.score(dist),coverage=coverage(dist),witness=witness)
        tree.reset_cache()
    first=SHRUG if tag=="rescue" else TRANCE
    reveal={};totals=[Counter(),Counter()]
    for route,p,k,obs in tree.expand(((choices(h)[first],()),)):
        if k!="decision":raise ValueError((k,obs))
        key=hand_key(obs);options=[]
        for seq in proposals(tag,obs):
            dist=tree.walk(obs,route,seq)
            options.append(dict(seq=seq,coverage=coverage(dist),v=tree.score(dist),dist=dist))
        best=[max(options,key=lambda x:(round(x["coverage"],9),x["v"][i])) for i in (0,1)]
        for i,b in enumerate(best):totals[i].update({k:p*w for k,w in b["dist"].items()})
        if key in reveal:raise ValueError("Duplicate exposed hand")
        reveal[key]=dict(p=p,events=route[0][1],options=options,best=[b["seq"] for b in best],best_values=[b["v"] for b in best])
        tree.reset_cache()
    for i,name in enumerate(("adaptive_v1","adaptive_v2")):
        dist=dict(totals[i]);lines[name]=dict(dist=dist,v=tree.score(dist),coverage=coverage(dist))
    for z in lines.values():assert abs(sum(z["dist"].values())-1)<1e-8
    assert abs(sum(z["p"] for z in reveal.values())-1)<1e-8
    raw=dict(tag=tag,lines=lines,reveal=reveal,states=tree.states,values=tree.scores,rpc=tree.rpc,seconds=perf_counter()-started)
    lane.close();host.close()
    with gzip.open(E/f"turn-probe-{tag}.gz","wt",compresslevel=5) as f:json.dump(raw,f,separators=(",",":"))

if __name__=="__main__":
    import sys
    measure(sys.argv[1])
