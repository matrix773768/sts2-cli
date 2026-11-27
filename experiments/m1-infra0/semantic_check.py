"""Correctness-only recorder and comparison. Exact canonical public fields, including floats."""
import gzip
import hashlib
import json
from pathlib import Path

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def observe(battle):
    import complete, options5d
    from policy5c import move
    events=[]
    request=battle.Lane.request
    current={}
    def rpc(lane,command,**kw):
        before=current.get(id(lane))
        result=request(lane,command,**kw)
        if command not in ("pre0_start","i1_n2_step") or "episode" not in result:return result
        episode=result["episode"]
        binding=move(before,before["actions"][kw["index"]]) if command=="i1_n2_step" else None
        obs=episode.get("observation")
        current[id(lane)]=lane.host.project(obs) if obs and episode["status"]=="active" else None
        state={k:episode.get(k) for k in ("status","actions","observed_c","public_law","pile_events","terminal_observation")}
        events.append([command,binding,digest(current[id(lane)]),digest(state)])
        return result
    battle.Lane.request=rpc
    build=complete.program
    def program(rows):
        table=build(rows)
        events.append(["compiled",digest(sorted((repr(k),v) for k,v in table.items()))])
        return table
    complete.program=options5d.program=program
    return events

def compare(left,right):
    def load(folder):
        worker=folder/"worker-0"
        metadata=json.loads((worker/"worker.json").read_bytes())
        path=worker/"evidence"/metadata["closed"]["file"]
        rows=list(map(json.loads,gzip.open(path)))
        for row in rows:row.pop("seconds",None)
        return rows,json.loads((worker/"semantic.json").read_bytes())
    x,steps=load(Path(left))
    y,other=load(Path(right))
    if x!=y or steps!=other or not steps:raise ValueError("Production record or public replay differed")
    return dict(rows=len(x),public_events=len(steps),record_sha256=digest(x),events_sha256=digest(steps))

if __name__=="__main__":
    import sys
    print(json.dumps(compare(*sys.argv[1:])))
