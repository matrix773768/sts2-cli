"""Replay both sides of the first public plan disagreement per domain, on native."""
from pathlib import Path
import sys
from time import perf_counter
from deploy import design, position, read, step, write
from native_checks import Lane, Bound, CounterCheck, check

def verify(out,folders,death=False):
    out.mkdir(parents=True,exist_ok=False)
    host,_=design.runtime(out)
    begin=perf_counter()
    results=[]
    seen=set()
    try:
        for d in folders:
            js={(j["id"],j["domain"]):j for j in read(d/"manifest.json")["jobs"]}
            for p in sorted(d.glob("*.json.gz")):
                r=read(p)
                dom=r["domain"]
                group=r["id"] if death else dom
                if group in seen or r["stop"]!="complete" or (death and (dom!="target" or group not in (14,18))):
                    continue
                for record in r["worlds"]:
                    ys=record["outcomes"]
                    if death and (ys["g2"]["status"],ys["plan_gate"]["status"])!=("predicted_win","death"):
                        continue
                    if ys["g2"]["utility"] is None or ys["plan_gate"]["utility"] is None or ys["g2"]["trace"]==ys["plan_gate"]["trace"]:
                        continue
                    j=js[r["id"],dom]
                    w=record["world"]
                    spec=j["spec"]|dict(seed=w["seed"])
                    fx={}
                    if dom!="natural":
                        fx.update(n4_order=w["order"])
                        if not dom.startswith("transfer_multi"):
                            fx["enemy_hp"]=j["enemy_hp"]
                        if j["counter"] is not None:
                            fx["relic_count"]=j["counter"]
                    for arm in ("g2","plan_gate"):
                        y=ys[arm]
                        left,right=Lane(host,0),Lane(host,1)
                        try:
                            log,_,st=position(left,j,w)
                            for a in y["trace"]:
                                h=host.project(st["observation"])
                                log.append([h,a])
                                st=step(left,st,a)
                            left.reset()
                            right.open()
                            native=CounterCheck(right,fx,[o["nunchaku"] for o,_ in log if o["decision"]["phase"]=="combat"])
                            ref=dict(steps=[dict(observation={k:v for k,v in o.items() if k!="nunchaku"},action=o["actions"][a]) for o,a in log],
                                terminal=y["terminal"]|dict(gold=y["gold"]),status=y["status"])
                            res=check(Bound(left,fx),native,[j["id"],spec],ref,host.runtime["targets"].project)
                        except (RuntimeError,ValueError,KeyError,AssertionError) as e:
                            res=dict(error=str(e))
                        finally:
                            left.close()
                            right.close()
                        results.append(dict(id=j["id"],domain=dom,seed=w["seed"],arm=arm,result=res))
                    seen.add(group)
                    break
    finally:
        host.close()
        write(out/"native.json",dict(seconds=perf_counter()-begin,rows=results))

if __name__=="__main__":
    verify(Path(sys.argv[1]),[Path(p) for p in sys.argv[2:] if p!="--death"],"--death" in sys.argv)
