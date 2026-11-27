"""Single-search generation comparison using the deployed V2 policy as the incumbent."""
from panel5e import E
from battle5d import configure
from complete import Evaluator
from deploy5b import load_net
from options5d import menu

class IncumbentPlanner:
    def __init__(self,base,planner,new_net):
        self.base=base
        self.planner=planner
        self.evaluate=Evaluator(new_net)

    def __call__(self,lane,h,past,net,g2,spec):
        options,states,main,query=menu(lane,h,past,self.base,g2,spec,self.planner)
        old=next((o for o in options if o.label==main),None)
        q=query|dict(incumbent=main,generation_switch=False,incumbent_available=old is not None,
                     scored_plans=len(options))
        if old is None:
            if query["use"]:raise ValueError("Missing executed incumbent")
            return {},{},q
        values=self.evaluate(states,spec)
        def score(o):return sum(p*(values[k] if kind=="C" else u) for kind,k,u,p in o.law)
        scores={o.label:score(o) for o in options}
        best=max(options,key=lambda o:scores[o.label])
        chosen=best if scores[best.label]>scores[main]+1 else old
        q.update(generation_switch=chosen is not old,incumbent_value=scores[main],chosen=chosen.label,
                 chosen_value=scores[chosen.label],use=chosen.label!="G2")
        return ({"execute":chosen.execute},{0:0},q) if q["use"] else ({},{},q)

def setup(out,name):
    host,g2,base,old=configure(out,"V2")
    net=load_net(E/(name.removeprefix("anchor-")+".pt"),name)
    return host,g2,net,IncumbentPlanner(base,old,net)
