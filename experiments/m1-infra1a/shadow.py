"""Observe original Planner calls. No cache result is returned to the running policy."""
from hashlib import sha256
import gzip
import json
from time import perf_counter_ns as clock
from common import OLD

def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def stamp(value):
    return sha256(encode(value)).hexdigest()

def name(fn):
    return None if fn is None else fn.__module__+"."+fn.__qualname__

class PublicInputs:
    def __init__(self,battle):
        self.public=None
        self.trail=None
        self.binding_ns=0
        self.inserted=False
        self.deployment=json.loads((OLD/"evidence/formal/deployment.json").read_bytes())
        self.static=stamp(["public-planner-v1",self.deployment["core5d"],self.deployment["core5e"],
                           self.deployment["runtime_sha256"],"V2-high",1.0,128])
        request=battle.Lane.request
        def watch(lane,cmd,**kw):
            result=request(lane,cmd,**kw)
            if cmd in ("pre0_start","i1_n2_step") and "episode" in result:
                start=clock()
                e=result["episode"]
                # Only the documented public wire, PileLaw and actual chosen menu
                # index enter the transcript. No opening recipe or shuffle command.
                self.public=[e.get("observation"),e.get("public_law"),e["actions"]]
                self.trail=stamp([None if cmd=="pre0_start" else self.trail,kw.get("index"),
                                  self.public,e.get("pile_events")])
                self.inserted |= any(v.startswith("insert:") for v in (e.get("pile_events") or []))
                self.binding_ns+=clock()-start
            return result
        battle.Lane.request=watch

    def key(self,plan,h,past,g2,opening):
        contract=[self.static,g2.identity,plan.graph_budget,plan.quotas,plan.reference_only,
                  name(plan.admit),plan.detail,name(plan.inspect)]
        if self.public is None or self.public[1] is None:
            raise AssertionError("Public observation or PileLaw unavailable")
        return stamp([contract,self.trail,self.public,h,past,128-self.public[2],opening["hp"],opening["max_hp"]])

class Shadow:
    def __init__(self,task,battle):
        import complete
        self.rows=[]
        self.position=(None,None,None)
        self.inputs=PublicInputs(battle)
        self.lookup={}
        planner=complete.Planner.__call__
        turn_search=complete.Turn.search
        self.best=None
        def record_best(turn,*args,**kw):
            self.best=turn_search(turn,*args,**kw)
            return self.best
        complete.Turn.search=record_best

        def measured(plan,lane,h,past,net,g2,opening):
            begin=clock()
            strict=self.inputs.key(plan,h,past,g2,opening)
            coarse=stamp([h,opening["hp"],opening["max_hp"]])
            key_ns=clock()-begin
            graph_inputs=[]
            saved=plan.inspect
            def inspect(*args):
                graph_inputs.append(args)
                if saved:saved(*args)
            plan.inspect=inspect
            self.best=None
            start=clock()
            try:
                g,ch,q=planner(plan,lane,h,past,net,g2,opening)
            except Exception as exc:
                self.rows.append(dict(location=self.position,key=strict,coarse=coarse,key_ns=key_ns,
                    elapsed_ns=clock()-start,error=type(exc).__name__+": "+str(exc)))
                raise
            finally:
                plan.inspect=saved
            elapsed=clock()-start
            # Capture executable public graph or policy table, full mass, options,
            # scalar probabilities, reference law and chosen conditional witnesses.
            _,_,laws,states,values,choices,options,ref_law,ref_first=graph_inputs[0]
            policy=(sorted((repr(k),v) for k,v in g["execute"].keywords["table"].items())
                    if "execute" in g else g["nodes"])
            witness=dict(graph=stamp(policy),choice=stamp(ch),laws=stamp(laws),
                         states=stamp(states),values=stamp(values),choices=stamp(choices),
                         options=stamp(options),reference=stamp([ref_first,ref_law]),
                         conditional=stamp(self.best),query=stamp(q))
            row=dict(location=self.position,key=strict,coarse=coarse,turn=h["turn"],action=self.inputs.public[2],
                     key_ns=key_ns,elapsed_ns=elapsed,query=q,output=witness,
                     bytes_policy=len(encode([policy,ch,q])),previous=self.lookup.get(strict))
            self.lookup.setdefault(strict,len(self.rows))
            self.rows.append(row)
            return g,ch,q
        complete.Planner.__call__=measured

    def phase(self,event,i,j,side):
        if event in ("root","side"):
            self.position=(i,j,side)

    def save(self,folder):
        with gzip.open(folder/"shadow.json.gz","wt",encoding="utf8") as f:
            json.dump(dict(binding_ns=self.inputs.binding_ns,rows=self.rows,deployment=self.inputs.static),f,separators=(",",":"))
