"""FIFO reference frontiers. Conditional depth-first expansion stays on the scalar entry point."""
from collections import Counter, deque
from functools import partial
import json
import os

from common import ROOT

COMMAND = "i1_infra1_reference_batch"
WIDTH = 32

def select_host(task, world=False):
    if task["variant"] in ("shadow","reuse"):
        return
    if not world and task["kind"] not in ("natural","pairs"):
        return  # Startup parent remains the frozen 5C builder.
    family="5e" if world else "5d"
    suffix="batch" if task["mode"]=="baseline" else "detail"
    if task["variant"]=="batch-attribution":suffix="attribution"
    variable="STS2_CORE5E_WORLD" if world else "STS2_CORE5C_HOST"
    os.environ[variable]=str(ROOT/"logs"/f"infra1a-{family}-{suffix}")

def reference(lane,h,past,g2,limit=48,observe=None,*,audit=None,metrics=None):
    import search5
    if observe is not None:
        return search5.reference(lane,h,past,g2,limit,observe)
    ctrl=search5.prepared(g2,h,past)
    def choose(obs,hist,score):
        index=int(score[0].argmax())
        return index,g2.encoder.update(hist,obs,obs["actions"][index])
    first,hist=choose(h,ctrl.history,ctrl.score([(h,ctrl.history)])[0])
    queue=deque([(1.,[dict(action=first,draws=[])],hist)])
    calls=0
    leaves=[]
    while queue and limit>0:
        size=min(WIDTH,limit,len(queue))
        ready=[queue.popleft() for _ in range(size)]
        limit-=size
        if metrics is not None:metrics.frontiers[size]+=1
        if size==1:
            raw=[lane.request("i1_core5_reference",route=ready[0][1])["response"]]
        else:
            requests=[dict(route=route,complete=True) for _,route,_ in ready]
            raw=lane.request(COMMAND,requests=requests)["results"]
        if len(raw)!=size:raise ValueError("Incomplete reference batch")
        observations={}
        for i,((_,route,hist),r) in enumerate(zip(ready,raw)):
            if r["kind"]=="decision" and len(route)+len(past)<128:
                observations[i]=(lane.host.project(r["state"]),hist)
        predicted=audit.evaluate(ctrl,observations) if audit and observations else {}
        for i,((p,route,hist),r) in enumerate(zip(ready,raw)):
            calls+=r["calls"]
            if i in observations:
                obs,_=observations[i]
                score=predicted[i] if i in predicted else ctrl.score([(obs,hist)])[0]
                action,after=choose(obs,hist,score)
                queue.append((p,route+[dict(action=action,draws=[])],after))
            elif r["kind"]=="R":
                support=r["support"]
                total=sum(support.values())
                for card,n in sorted(support.items(),key=lambda kv:(-kv[1],kv[0])):
                    edge=route[-1]
                    queue.append((p*n/total,route[:-1]+[edge|dict(draws=edge["draws"]+[card])],hist))
            else:
                leaves.append(r|dict(probability=p))
    leaves.extend(dict(kind="deferred",probability=p) for p,_,_ in queue)
    if abs(sum(r["probability"] for r in leaves)-1)>1e-8:raise ValueError("Reference lost mass")
    return leaves,calls,first

class ScoreAudit:
    def __init__(self):
        self.counts=Counter()
        self.examples=[]
        self.maximum=[0.,0.]

    def evaluate(self,ctrl,observations):
        import numpy as np
        from time import perf_counter_ns
        inputs=list(observations.values())
        if len(inputs)==1:return {}
        if not self.counts["encoding_checks"]:
            from hashlib import sha256
            encoder=ctrl.model.encoder
            encode=encoder.encode
            signatures=[]
            def trace(*args,**kw):
                row=encode(*args,**kw)
                raw=json.dumps(row,sort_keys=True,separators=(",",":"),default=lambda x:x.tolist(),allow_nan=False)
                signatures.append(sha256(raw.encode()).hexdigest())
                return row
            encoder.encode=trace
            try:
                ctrl.score([inputs[0]])
                ctrl.score(inputs)
            finally:
                encoder.encode=encode
            if signatures[0]!=signatures[1]:raise ValueError("G2 encoding depends on batch")
            self.first_encoding=signatures[0]
            self.counts["encoding_checks"]+=1
        start=perf_counter_ns()
        individual=[ctrl.score([x])[0] for x in inputs]
        mid=perf_counter_ns()
        batched=ctrl.score(inputs)
        self.counts["batch_ns"]+=perf_counter_ns()-mid
        self.counts["individual_ns"]+=mid-start
        self.counts["groups"]+=1
        self.counts["size_"+str(len(inputs))]+=1
        for (obs,_),a,b in zip(inputs,individual,batched,strict=True):
            self.counts["nodes"]+=1
            changed=[]
            for j,name in enumerate(("scores","probabilities")):
                if a[j].shape!=b[j].shape:raise ValueError("G2 result shape changed")
                delta=float(np.max(np.abs(a[j]-b[j])))
                self.maximum[j]=max(self.maximum[j],delta)
                if not np.array_equal(a[j],b[j]):
                    self.counts[name+"_different"]+=1
                    changed.append(name)
            self.counts["ranking_different"]+=int(not np.array_equal(np.argsort(-a[0],kind="stable"),np.argsort(-b[0],kind="stable")))
            self.counts["argmax_different"]+=int(a[0].argmax()!=b[0].argmax())
            if changed and len(self.examples)<3:
                self.examples.append(dict(turn=obs["turn"],scalar_scores=a[0].tolist(),batch_scores=b[0].tolist(),
                                          scalar_probability=a[1].tolist(),batch_probability=b[1].tolist()))
        return dict(zip(observations,individual,strict=True))  # Only frozen singleton scores drive decisions.

    def save(self,folder):
        (folder/"g2-check.json").write_text(json.dumps(dict(counts=self.counts,maximum=self.maximum,examples=self.examples,first_encoding=getattr(self,"first_encoding",None))))

class BatchMetrics:
    def __init__(self,battle,check_exports=False):
        from hashlib import sha256
        self.frontiers=Counter()
        self.exports=Counter()
        # A projection digest identifies returned public bytes only.
        seen={}
        message=0
        self.transport=Counter()
        request=battle.Lane.request
        def measured(lane,cmd,**kw):
            nonlocal message
            if check_exports and (cmd in ("pre0_start","i1_n2_step","pre0_abandon","i1_n2_close")
                                  or cmd=="i1_core5_reference" and "route" not in kw):
                seen.clear()
            if cmd==COMMAND:
                parts=kw["requests"]
            elif cmd=="i1_core5_reference" and "route" in kw:
                parts=[kw]
            else:
                return request(lane,cmd,**kw)
            self.transport["route_messages"]+=1
            self.transport["logical_routes"]+=len(parts)
            self.transport["edges"]+=sum(len(item["route"]) for item in parts)
            if cmd==COMMAND:self.transport["batched_routes"]+=len(parts)
            result=request(lane,cmd,**kw)
            if check_exports:
                message+=1
                responses=result["results"] if cmd==COMMAND else [result["response"]]
                for row in responses:
                    if row["kind"]!="decision":continue
                    raw=json.dumps(row["state"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()
                    key=sha256(raw).digest()
                    self.exports["decisions"]+=1
                    if key in seen:
                        scope="same_message" if seen[key]==message else "earlier_message"
                        self.exports[scope]+=1
                        self.exports[scope+"_canonical_bytes"]+=len(raw)
                    seen[key]=message
                self.exports["peak_unique_per_epoch"]=max(self.exports["peak_unique_per_epoch"],len(seen))
            return result
        battle.Lane.request=measured

    def save(self,folder):
        (folder/"batch-metrics.json").write_text(json.dumps(dict(frontiers=self.frontiers,transport=self.transport,exports=self.exports)))

def install(task,battle,pairs):
    import complete
    if task["variant"]=="reuse":
        from reuse import PublicReuse
        return PublicReuse(task,battle)
    if task["variant"]=="shadow":
        from shadow import Shadow
        return Shadow(task,battle)
    audit=ScoreAudit() if task["variant"]=="g2-check" else None
    check_exports=task["variant"]=="batch-attribution" and task["kind"]=="audit"
    metrics=BatchMetrics(battle,check_exports) if task["mode"]=="aggregate" else None
    complete.reference=partial(reference,audit=audit,metrics=metrics)
    return audit or metrics
