"""Differential Planner calls on identical public inputs in independently reordered worlds."""
import json
from pathlib import Path
from hashlib import sha256

def fingerprint(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def install(task):
    import options5d,complete
    original=options5d.menu
    receipts=[]
    def menu(lane,h,past,net,g2,spec,plan):
        if not receipts:
            for seed in (131,977,8111):
                changed=lane.request("i1_core5_reference",diagnostic_world=seed)["response"]
                if lane.host.project(changed["state"])!=h:raise ValueError("Public root changed")
                fresh=complete.Planner(net)
                captured=[]
                fresh.inspect=lambda *a:captured.append(a)
                g,ch,q=fresh(lane,h,past,net,g2,spec)
                _,_,laws,states,values,choices,opts,ref,first=captured[0]
                program=sorted((repr(k),v) for k,v in g["execute"].keywords["table"].items()) if "execute" in g else g["nodes"]
                receipts.append(dict(public=fingerprint([h,past,changed["law"]]),graph=fingerprint(program),
                    choice=fingerprint(ch),q=fingerprint(q),candidate=fingerprint([laws,states,values,choices,opts]),
                    reference=fingerprint([ref,first])))
            if any(r!=receipts[0] for r in receipts):raise ValueError("Hidden-world fairness mismatch")
        return original(lane,h,past,net,g2,spec,plan)
    options5d.menu=menu
    class Save:
        def save(self,folder):
            if len(receipts)!=3:raise ValueError("Missing hidden-world test")
            (folder/"infra1h-fair.json").write_text(json.dumps(receipts,indent=2))
    return Save()
