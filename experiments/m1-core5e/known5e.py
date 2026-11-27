"""Open historical failures: cross-score historical policies and replay each fixed model."""
import json
from time import perf_counter
from panel5e import D,E,OUT,load
from battle5e import setup_arm
from options5d import menu
from experience5d import restore
from deploy5b import Lane,fight
def run():
    start=perf_counter();out=OUT/"known";out.mkdir(parents=True,exist_ok=True)
    models={};host=None
    for arm in ("V2","V3","mc","td"):
        current,g2,net,plan=setup_arm(out,arm);models[arm]=(net,plan)
        if host is None:host=current
        else:current.close()
    panel=load(D/"panel.gz")["confirm"];lane=Lane(host,0);report=[]
    for old in json.loads((D/"flips.json").read_bytes())["cases"]:
        w=panel[old["i"]];s=w["spec"];turn=old["turn"]
        trace=[];net,plan=models["V2"]
        fight(lane,g2,s,"V2",net,planner=plan,trace=trace);lane.reset()
        trace=[(h["turn"],idx) for h,idx in trace]
        case=dict(family=w["family"],seed=s["seed"],turn=turn,encounter=s["encounter"],policies={},whole={})
        for arm,(net,plan) in models.items():
            st,past=restore(lane,s,trace,turn);h=host.project(st["observation"])
            options,states,main,q=menu(lane,h,past,net,g2,s,plan)
            opt=next((o for o in options if o.label==main),None)
            cross={}
            if opt:
                for other,(_,planner) in models.items():
                    v=planner.evaluator(states,s)
                    cross[other]=sum(p*(v[k] if kind=="C" else u) for kind,k,u,p in opt.law)
            case["policies"][arm]=dict(main=main,first=opt.first if opt else None,law=opt.law if opt else None,
                                      use=q["use"],cross=cross)
            lane.reset()
            result=fight(lane,g2,s,arm,net,planner=plan);lane.reset()
            case["whole"][arm]=dict(status=result["status"],terminal=result["terminal"])
        report.append(case)
    lane.close();host.close()
    (E/"known.json").write_text(json.dumps(dict(cases=report,seconds=perf_counter()-start),indent=2))
if __name__=="__main__":run()
