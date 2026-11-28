"""Opt-in complete-turn transaction. Every abandoned search restarts on corrected 1A."""
import json
import os
from pathlib import Path
import sys
from time import perf_counter_ns
from collections import Counter

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def select_host(task,world=False):
    if world:
        os.environ["STS2_CORE5E_WORLD"]=str(ROOT/"logs/infra1h-5e-base2")
    elif task["kind"] in ("natural","pairs"):
        name="infra1h2/5d-batch" if task["kind"]=="natural" and task["variant"]=="h-state" else "infra1h-5d-base2"
        os.environ["STS2_CORE5C_HOST"]=str(ROOT/"logs"/name)

def install(task,battle,pairs):
    sys.path.insert(0,str(HERE.parent/"m1-infra1a"))
    import execution
    observer=execution.install(task|dict(variant="batch"),battle,pairs)
    if task["kind"]!="natural":return observer
    from complete import Planner
    if task["variant"]=="h-state-control":
        frozen=Planner.__call__
        costs=Path(task["folder"])/"baseline-query-cost.jsonl"
        def timed(self,lane,h,past,net,g2,spec):
            before=perf_counter_ns()
            result=frozen(self,lane,h,past,net,g2,spec)
            cost=dict(seed=spec["seed"],turn=h["turn"],calls=result[2]["calls"],seconds=(perf_counter_ns()-before)/1e9)
            with costs.open("a",encoding="utf8") as file:file.write(json.dumps(cost)+"\n")
            return result
        Planner.__call__=timed
        return observer
    from lane import BranchLane,Unsupported,token
    from tactics import CARDS
    import complete
    reference=complete.reference
    def marked_reference(lane,*args,**kw):
        hot=lane.lane if isinstance(getattr(lane,"lane",None),BranchLane) else None
        if hot is None:return reference(lane,*args,**kw)
        previous=hot.stage;hot.stage="reference"
        try:return reference(lane,*args,**kw)
        finally:hot.stage=previous
    complete.reference=marked_reference
    request=battle.Lane.request
    planner=Planner.__call__
    path=Path(task["folder"])/"hot-turns.jsonl"
    def observe(self,command,**kw):
        r=request(self,command,**kw)
        if command in ("pre0_start","i1_n2_reset","i1_n2_step"):self.h2_episode=r.get("episode")
        return r
    def dispatch(self,lane,h,past,net,g2,spec):
        start=perf_counter_ns();branch=None
        receipt=dict(seed=spec["seed"],turn=h["turn"])
        try:
            if h["turn"]!=1 or past:raise Unsupported("nonopening_turn")
            if spec["encounter"]!="MECHA_KNIGHT_ELITE":raise Unsupported("encounter/"+spec["encounter"])
            st=getattr(lane,"h2_episode",None)
            if not st or not st.get("observation") or lane.host.project(st["observation"])!=h:raise Unsupported("opening/not_observed")
            wire=st["observation"]
            opening=next((c["id"] for c in wire["hand"] if c["id"] not in CARDS),None)
            if opening:raise Unsupported("graph/card/"+opening)
            belief=st.get("public_law")
            bag=Counter(map(token,wire["deck"]));bag.subtract(map(token,wire["hand"]))
            if not isinstance(belief,dict) or belief.get("counts")!=dict(+bag) or any(belief.get(k) for k in
                    ("top","bottom","membership_gap","order_gap","shuffles")):raise Unsupported("opening/pile_law")
            branch=BranchLane(lane,wire,spec,law=belief)
            # The frozen Planner owns its V2 evaluator cache. A candidate owns all of
            # its branch state and its inference cache until this transaction ends.
            from copy import copy
            from search5 import Evaluator
            candidate=copy(self);candidate.evaluator=Evaluator(net)
            result=planner(candidate,branch,h,past,net,g2,spec)
            if self.detail:self.last=candidate.last
            receipt.update(committed=True,logical_calls=result[2]["calls"],seconds=(perf_counter_ns()-start)/1e9)
            return result
        except Unsupported as error:
            receipt.update(committed=False,reason=str(error),attempt_seconds=(perf_counter_ns()-start)/1e9)
            fallback=perf_counter_ns()
            result=planner(self,lane,h,past,net,g2,spec)
            receipt.update(fallback_seconds=(perf_counter_ns()-fallback)/1e9,logical_calls=result[2]["calls"])
            return result
        finally:
            if branch is not None:
                receipt["physical"]=dict(branch.physical)
                branch.close()
            with path.open("a",encoding="utf8") as f:f.write(json.dumps(receipt)+"\n")
    battle.Lane.request=observe
    Planner.__call__=dispatch
    return observer
