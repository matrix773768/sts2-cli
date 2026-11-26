"""Targeted independent native replay, including a counter read at each combat menu."""
from pathlib import Path
import re
import sys
from time import perf_counter
from design import BUILD,CFG,LOGS,Host,choices,cohort,digest,jobs,position,read,runtime,step,write
from loop_battle import Lane
from native import check
from targeted_replay import Bound


class CounterCheck(Bound):
    def __init__(self,lane,fx,expected):
        super().__init__(lane,fx)
        self.expected=expected
        self.values=[]

    def request(self,cmd,**args):
        res=super().request(cmd,**args)
        if cmd=="i1_iid_native_roster":
            text=self.lane.request("synthetic_snapshot")["continuation"]
            match=re.search(r"mirrorRelics=[^;]*?NUNCHAKU/(\d+)",text)
            value=int(match.group(1))%10 if match else None
            if value!=self.expected[len(self.values)]:
                raise ValueError(f"Native Nunchaku mismatch {value}, projected {self.expected[len(self.values)]}")
            self.values.append(value)
        return res


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    host,m=runtime(out)
    base=host.runtime["targets"].project
    js=jobs()
    report=[]
    t=perf_counter()
    for idx in (80,81,92):
        j=js[idx]
        for n in j["counts"]:
            r=read(next(LOGS.glob(f"n4b-finalcore-*/{idx:03}-{n}.json.gz")))
            if r["stop"]!="complete":
                report.append(dict(id=idx,n=n,stop=r["stop"]))
                continue
            for w in r["worlds"]["reference"][:2]:
                spec=j["spec"]|dict(seed=w["seed"],relics=[] if n is None else ["NUNCHAKU"])
                fx=dict(n4_order=w["order"],enemy_hp=j["enemy_hp"])
                if n is not None:
                    fx["relic_count"]=n
                rec=w["results"]["0"]
                y=rec["outcomes"][rec["refs"]["plan_atk"]]
                l,p=Lane(host,0),Lane(host,1)
                try:
                    hist,h,st=position(l,j,n,w)
                    new=choices(l,m,h,hist)
                    assert r["paths"]==new["paths"] and h==r["h"] and hist==r["history"]
                    log=hist.copy()
                    for a in y["trace"]:
                        o=host.project(st["observation"])
                        assert o["enemies"] or o["decision"].get("effect")!="MoveToDrawTop"
                        log.append([o,a])
                        st=step(l,st,a)
                    l.reset()
                    p.open()
                    expected=[o["nunchaku"] for o,a in log if o["decision"]["phase"]=="combat"]
                    native=CounterCheck(p,fx,expected)
                    row=dict(steps=[dict(observation={k:v for k,v in o.items() if k!="nunchaku"},action=o["actions"][a]) for o,a in log],
                        status=y["status"],terminal=y["terminal"]|dict(gold=y["gold"]))
                    result=check(Bound(l,fx),native,[idx,spec],row,base)
                    report.append(dict(id=idx,n=n,seed=w["seed"],graph_match=True,native=result,counts=native.values))
                except (RuntimeError,ValueError,AssertionError) as e:
                    report.append(dict(id=idx,n=n,seed=w["seed"],error=str(e)))
                finally:
                    l.close()
                    p.close()
    host.close()
    write(out/"checks.json",dict(results=report,seconds=perf_counter()-t))


if __name__=="__main__":
    run(Path(sys.argv[1]))
