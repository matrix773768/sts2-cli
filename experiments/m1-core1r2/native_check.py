"""Replay the first four fixed development prefixes and compare the terminal with native."""
import argparse
from pathlib import Path
import sys
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core1"))
from compare import episode,check,Lane,read,runtime,write


class AuditLane(Lane):
    completed_steps=0

    def request(self,op,**kwargs):
        reply=super().request(op,**kwargs)
        if op=="i1_n2_step": self.completed_steps+=1
        return reply


def run(out,panel):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host,model=runtime(out)
    rows=[]
    try:
        jobs={j["family"]:j for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"] if j["split"]=="development"}
        for i,row in enumerate(read(panel/"panel.json")["rows"][:4]):
            family=row["family"]
            history=read(panel/(family+".json.gz"))["history"]
            history=[({k:v for k,v in o.items() if k not in ("order_hooks","tuning_fork")},a) for o,a in history]
            left,right=AuditLane(host,1),Lane(host,2)
            try:
                # G2 is used only after all CORE-1R witness actions, for this terminal audit.
                ref=episode(host,model,jobs[family],0,history,True)
                left.open()
                right.open()
                result=check(left,right,[i,jobs[family]["spec"]],ref,host.runtime["targets"].project)
                rows.append(dict(family=family,witness_actions=len(history),total_actions=len(ref["steps"]),result=result))
            except (ValueError,RuntimeError,AssertionError,TypeError,KeyError) as err:
                rows.append(dict(family=family,error=repr(err),witness_actions=len(history),
                                 matched_steps=left.completed_steps))
            finally:
                left.close()
                right.close()
    finally:
        host.close()
        write(out/"native.json",dict(rows=rows,seconds=perf_counter()-start))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("panel",type=Path)
    a=p.parse_args()
    run(a.out,a.panel)
