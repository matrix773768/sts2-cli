"""Measure legacy G2-search counters against the recorded first-seed fights."""
from core4_roots import *
from train_value4 import rows,Counter

def run(out,logs):
    t=perf_counter();logs.mkdir(parents=True,exist_ok=False)
    prior={r["family"]:r for r in rows(out/"test-G2search-0.gz")}
    host,model=setup(logs);lane=Lane(host,0);model.budget=24;counts=Counter();matches=0
    for job in panels()["confirm"]:
        st=cohort.start(lane,spec_for(job,"test"));h=host.project(st["observation"])
        ctrl=prepared(model,h,[]);ctrl.project=host.project
        while st["status"]=="active" and st["actions"]<128:
            h=host.project(st["observation"]);a,_,_=ctrl.act(h,lane,st["actions"])
            st=step(lane,st,a);ctrl.after(st)
        r=prior[job[3]]
        if r["status"]==st["status"] and r["actions"]==st["actions"] and r["terminal"]["hp"]==st["terminal_observation"]["hp"]:matches+=1
        counts.update(ctrl.counts);lane.reset()
    lane.close();host.close()
    (out/"reference-cost.json").write_text(json.dumps(dict(matched=matches,counts=counts,seconds=perf_counter()-t),indent=2))

if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
