"""Repeat the first two changed V1 test fights, then execute their public witnesses on native."""
from play_loop import fight,load_net
from core4_roots import *
from design import runtime
sys.path.insert(0,str(HERE.parent/"m1-core1"))
from compare import episode,check

def run(out,logdir):
    start=perf_counter();logdir.mkdir(parents=True,exist_ok=False)
    import torch
    torch.set_num_threads(1)
    rows={r["family"]:r for f in sorted(out.glob("test-v1-*.gz")) for line in gzip.open(f) for r in [json.loads(line)]}
    jobs=[j for j in panels()["confirm"] if any(q["used"] for q in rows[j[3]].get("queries",[]))][:2]
    host,g2=setup(logdir);lane=Lane(host,0);net=load_net(out/"v1.pt","v1");traces=[]
    for j in jobs:
        spec=spec_for(j,"test");trace=[];result=fight(lane,g2,spec,"v1",net,trace=trace);lane.reset()
        assert len(trace)==result["actions"] and trace
        assert result["terminal"]==rows[j[3]]["terminal"]
        traces.append((j,spec,[({k:v for k,v in o.items() if k not in ("order_hooks","tuning_fork")},a) for o,a in trace]))
    lane.close();host.close()
    native,model=runtime(logdir);audits=[]
    for j,spec,forced in traces:
        left,right=Lane(native,1),Lane(native,2)
        try:
            ref=episode(native,model,dict(spec=spec),0,forced,True)
            left.open();right.open();audit=check(left,right,[j[0],spec],ref,native.runtime["targets"].project)
        except (AssertionError,ValueError,KeyError,RuntimeError) as e:audit=dict(error=repr(e))
        finally:left.close();right.close()
        audits.append(dict(family=j[3],forced=len(forced),audit=audit))
    native.close();(out/"audit.json").write_text(json.dumps(dict(rows=audits,seconds=perf_counter()-start),indent=2))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
