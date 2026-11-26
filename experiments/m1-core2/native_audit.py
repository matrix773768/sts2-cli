"""Audit two prespecified complete trajectories through the independent native adapter."""
from state import *
from time import perf_counter
sys.path.insert(0,str(HERE.parent/"m1-core1"))
from compare import runtime,episode,check,Lane,read,write

def run(out,records):
    out.mkdir(parents=True,exist_ok=False)
    t=perf_counter()
    jobs={j["family"]:j for j in read(HERE.parent/"m1-core1/benchmark.json")["jobs"] if j["split"]=="development"}
    host,model=runtime(out)
    rows=[]
    try:
        for row in (r for chunk in batches(records) for r in chunk if r["source"]=="trajectory"):
            family=row["family"]
            history=[({k:v for k,v in o.items() if k not in ("order_hooks","tuning_fork")},a) for o,a in row["history"]]
            left,right=Lane(host,1),Lane(host,2)
            try:
                ref=episode(host,model,jobs[family],0,history,True)
                assert len(ref["steps"])==len(history)
                left.open()
                right.open()
                result=check(left,right,[len(rows),jobs[family]["spec"]],ref,host.runtime["targets"].project)
                rows.append(dict(family=family,steps=len(history),result=result))
            except (RuntimeError,ValueError,AssertionError) as err:rows.append(dict(family=family,error=str(err)))
            finally:left.close();right.close()
            if len(rows)==2:break
    finally:host.close()
    write(out/"native.json",dict(rows=rows,seconds=perf_counter()-t))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
