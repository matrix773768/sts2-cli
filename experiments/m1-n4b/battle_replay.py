"""Replay the first divergent route in each deployment domain/budget using the actual native game."""
from pathlib import Path
import sys
from time import perf_counter
from design import LOGS,cohort,jobs,read,runtime,step,write
from native_checks import Bound,CounterCheck,Lane,check
from battles import scenario


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,_=runtime(out)
    base=host.runtime["targets"].project
    js=jobs()
    t=perf_counter()
    results=[]
    for domain in ("natural","target"):
        for budget in (0,24):
            selected=False
            for p in sorted((LOGS/"n4b-battle-17").glob("*.gz")):
                row=read(p)
                if row["domain"]!=domain:
                    continue
                baseline=read(LOGS/"n4b-battle-0"/p.name)
                for w,b in zip(row["worlds"],baseline["worlds"],strict=True):
                    y=w["outcomes"][f"counter_pair-17/{budget}"]
                    old=b["outcomes"][f"G2/{budget}"]
                    assert w["seed"]==b["seed"]
                    if y["trace"]==old["trace"]:
                        continue
                    j,n=js[row["id"]],row["counter"]
                    if domain=="natural":
                        spec=j["source_spec"]|dict(seed=w["seed"],hp=row["initial_hp"],max_hp=max(80,row["initial_hp"]))
                        fx={}
                    else:
                        spec=j["spec"]|dict(seed=w["seed"],relics=[] if n is None else ["NUNCHAKU"])
                        fx=dict(n4_order=w["order"],enemy_hp=j["enemy_hp"])
                        if n is not None:
                            fx["relic_count"]=n
                    for name,terminal in (("G2",old),("counter_pair",y)):
                        l,p2=Lane(host,0),Lane(host,1)
                        try:
                            log,h,st=scenario(l,j,n,w,domain=="natural")
                            for a in terminal["trace"]:
                                o=host.project(st["observation"])
                                log.append([o,a])
                                st=step(l,st,a)
                            l.reset()
                            p2.open()
                            native=CounterCheck(p2,fx,[o["nunchaku"] for o,a in log if o["decision"]["phase"]=="combat"])
                            rr=dict(steps=[dict(observation={k:v for k,v in o.items() if k!="nunchaku"},action=o["actions"][a]) for o,a in log],
                                terminal=terminal["terminal"]|dict(gold=terminal["gold"]),status=terminal["status"])
                            evidence=check(Bound(l,fx),native,[j["id"],spec],rr,base)
                        except (ValueError,RuntimeError,AssertionError) as exc:
                            evidence=dict(error=str(exc))
                        finally:
                            l.close()
                            p2.close()
                        results.append(dict(id=j["id"],counter=n,domain=domain,budget=budget,arm=name,evidence=evidence))
                    selected=True
                    break
                if selected:
                    break
    host.close()
    write(out/"native.json",dict(seconds=perf_counter()-t,results=results))


if __name__=="__main__":
    run(Path(sys.argv[1]))
