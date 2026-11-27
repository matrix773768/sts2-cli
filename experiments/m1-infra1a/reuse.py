"""Bounded normal-suffix memoization. Replay evaluator requests to preserve its numerical/LRU context."""
from collections import Counter, OrderedDict
from time import perf_counter_ns as clock
from common import json

class PublicReuse:
    def __init__(self,task,battle):
        import complete
        from shadow import PublicInputs
        self.inputs=PublicInputs(battle)
        self.cache=OrderedDict()
        self.stats=Counter()
        self.hits=[]
        self.world=None
        self.side=None
        self.root=None
        base=complete.Planner.__call__

        def query(plan,lane,h,past,net,g2,opening):
            law=self.inputs.public[1] if self.inputs.public else None
            if self.side is None or self.inputs.inserted or plan.inspect or plan.detail or not law or law.get("membership_gap") or law.get("order_gap"):
                return base(plan,lane,h,past,net,g2,opening)
            begin=clock()
            key=self.inputs.key(plan,h,past,g2,opening)
            self.stats["key_ns"]+=clock()-begin
            self.stats["eligible"]+=1
            evaluator=plan.evaluator
            if key in self.cache:
                value,tape=self.cache.pop(key)
                saved=evaluator.cache.copy(),evaluator.hits,evaluator.misses
                start=clock()
                match=all(evaluator(states,opening)==expected for states,expected in tape)
                self.stats["model_guard_ns"]+=clock()-start
                if match:
                    self.cache[key]=(value,tape)
                    lane.request("i1_core5_reference",clear=True)
                    self.stats["hits"]+=1
                    g,ch,q=value
                    self.stats["logical_sim_calls_reused"]+=q["calls"]
                    self.hits.append(dict(key=key,location=[self.root,self.world,self.side],turn=h["turn"],calls=q["calls"]))
                    return g,ch.copy(),q.copy()
                evaluator.cache,evaluator.hits,evaluator.misses=saved
                self.stats["numeric_fallback"]+=1
            tape=[]
            def record(states,context):
                values=evaluator(states,context)
                tape.append((states,values.copy()))
                return values
            plan.evaluator=record
            try:
                result=base(plan,lane,h,past,net,g2,opening)
            finally:plan.evaluator=evaluator
            self.cache[key]=(result,tape)
            if len(self.cache)>32:
                self.cache.popitem(last=False)
            self.stats["max_entries"]=max(self.stats["max_entries"],len(self.cache))
            return result
        complete.Planner.__call__=query

    def phase(self,event,root,world,side):
        if event=="root":
            self.cache.clear()
            self.root=root
            self.side=None
        elif event=="execute":
            # The production sampler has verified an exchangeable tail and instance law.
            self.inputs.inserted=False
            self.side=side
            self.world=world
        elif event=="side_end":
            self.side=None

    def save(self,folder):
        self.stats["transcript_ns"]=self.inputs.binding_ns
        (folder/"reuse.json").write_text(json.dumps(dict(stats=self.stats,hits=self.hits)))
