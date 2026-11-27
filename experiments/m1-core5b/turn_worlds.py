"""One-turn interventions on the recorded world and independent conditional draw-pile permutations."""
import sys
from turn_probe import *
from play_loop import prepared,execute
from semantic import encode
from hashlib import sha256

def model_key(c):
    arrays=encode(c)
    return sha256(b"".join(z.tobytes() for z in arrays)).hexdigest()

def choose_g2(lane,h,past,g2,position):
    ctrl=prepared(g2,h,past);ctrl.project=lane.host.project
    return ctrl.act(h,lane,position)[0]

def continue_high(lane,st,past,g2,net,plan,spec):
    lock=None
    while st["status"]=="active" and st["actions"]<128:
        h=lane.host.project(st["observation"]);before=st["actions"]
        if h["decision"]["phase"]=="combat" and h["turn"]!=lock:
            lock=h["turn"];graph,choice,q=plan(lane,h,past,net,g2,spec)
            if q["use"]:
                st,played,_=execute(lane,st,graph,choice,choice.get(0));past.extend(played)
        if before==st["actions"]:
            a=choose_g2(lane,h,past,g2,before);past.append((h,a));st=step(lane,st,a)
    return st

def trial(lane,d,past,probe,name,world,g2,net,plan,values,trace=None):
    st=restore(lane,d,past);past=past.copy()
    if world is not None:
        r=lane.request("i1_core5_reference",diagnostic_world=world)["response"]
        assert lane.host.project(r["state"])==d["right"]["snapshot"]["h"]
        assert r["law"]==st["public_law"]
    rule=probe["lines"].get(name,{})
    adaptive=name.startswith("adaptive")
    remaining=([SHRUG] if d["tag"]=="rescue" else [TRANCE]) if adaptive else [tuple(v) for v in rule.get("moves",())]
    actual=[];reveal=None;value=None;c=None
    while st["status"]=="active":
        h=lane.host.project(st["observation"])
        if h["turn"]!=d["turn"]:break
        if name=="reference":
            a=choose_g2(lane,h,past,g2,st["actions"])
        else:
            if adaptive and len(actual)==1:
                reveal=hand_key(h)
                remaining=[tuple(v) for v in probe["reveal"][reveal]["best"][int(name=="adaptive_v2")]]
            move,remaining=select(h,remaining);a=choices(h)[move]
        desc=description(h,a)
        if desc["kind"]=="select_candidate":desc["selected_card"]=h["decision"]["candidates"][desc["choice"]]
        actual.append(dict(action=desc,hand=hand_key(h),energy=h["energy"]))
        past.append((h,a));st=step(lane,st,a)
        if st.get("observed_c"):
            c=st["observed_c"];k=model_key(c);value=values.get(k)
            if name!="reference" and value is None:raise ValueError(("C outside public law",name,world,k))
            if name!="reference" and k not in rule["keys"]:raise ValueError(("C outside chosen policy",name,world))
    st=continue_high(lane,st,past,g2,net,plan,d["spec"])
    if trace is not None:trace.extend(past)
    return dict(name=name,world=world,reveal=reveal,actions=actual,C=c if world is None else None,
        next_hp=c["hp"] if c else None,actual_v=value,status=st["status"],terminal=st.get("terminal_observation"))

def run(tag,shard,n):
    start=perf_counter();d=source(tag);probe=json.load(gzip.open(E/f"turn-probe-{tag}.gz"))
    keymap={k:model_key(c) for k,c in probe["states"].items() if c.get("schema")=="sts2.core.c.v3"}
    values={keymap[k]:v for k,v in probe["values"].items() if k in keymap}
    for line in probe["lines"].values():
        line["keys"]={keymap[k] for k in line["dist"] if k in keymap}
    out=LOGS/f"turn-worlds-{tag}-{shard}";out.mkdir(exist_ok=True)
    old,g2,v2,plan=init(out,"high");old.close()
    host=host_at(out,ROOT/"logs/core5b-turn-review-host");lane=Lane(host,0)
    past=prefix(lane,g2,v2,d);rows=[]
    # Seeds fixed independently of realized card identities and fighting outcomes.
    worlds=[None]+[int(sha256(f"5b-turn-v1/{tag}/{i}".encode()).hexdigest()[:7],16) for i in range(48)]
    for world in worlds[shard::n]:
        for name in [*probe["lines"],"reference"]:
            r=trial(lane,d,past,probe,name,world,g2,v2,plan,values);lane.reset()
            if world is None and name=="deployed":
                assert r["status"]==d["right"]["row"]["status"] and r["terminal"]["hp"]==d["right"]["row"]["terminal"]["hp"]
            rows.append(r)
    host.close();lane.close()
    with gzip.open(E/f"turn-worlds-{tag}-{shard}.gz","wt") as f:json.dump(dict(rows=rows,seconds=perf_counter()-start),f,separators=(",",":"))

if __name__=="__main__":run(sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))
