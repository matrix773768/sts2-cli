"""Post-confirmation attribution at the first divergent turn on the two high-budget losses."""
import json,gzip
from time import perf_counter
from panel5d import E,OUT,load
from results5d import group
from experience5d import restore
from options5d import menu
from battle5d import configure
from deploy5b import Lane,fight
from play_loop import step
from policy5c import move
from assessment import utility

def run():
    t=perf_counter();out=OUT/"flips";out.mkdir(parents=True,exist_ok=True)
    host,g2,v2,p2=configure(out,"V2")
    other,_,v3,p3=configure(out,"V3");other.close()
    lane=Lane(host,0);models={"V2":(v2,p2),"V3":(v3,p3)}
    original={a:{r["i"]:r for r in group("confirm-"+a+"-*")} for a in models}
    panel=load(E/"panel.gz")["confirm"];reports=[]
    for i,w in enumerate(panel):
        if original["V2"][i]["status"]==original["V3"][i]["status"]:continue
        s=w["spec"]; traces={};reports.append(case:=dict(i=i,family=w["family"],seed=s["seed"],encounter=s["encounter"]))
        for arm,(net,plan) in models.items():
            trace=[];res=fight(lane,g2,s,arm,net,trace=trace,planner=plan)
            assert res["terminal"]==original[arm][i]["terminal"]
            traces[arm]=[(h["turn"],idx) for h,idx in trace];lane.reset()
        dif=next(j for j,(a,b) in enumerate(zip(traces["V2"],traces["V3"])) if a!=b)
        turn=traces["V2"][dif][0]
        by_arm={}
        for arm,(net,plan) in models.items():
            st,past=restore(lane,s,traces[arm],turn);h=host.project(st["observation"])
            opts,states,main,q=menu(lane,h,past,net,g2,s,plan)
            selected=next((opt for opt in opts if opt.label==main),None)
            result=dict(main=main,used=q["use"],ref_coverage=q["reference_coverage"],reference=q["reference"],best=q["value"],
                        actual=[],suffix={})
            if selected:
                result["cross_values"]={}
                for key,(_,p) in models.items():
                    vals=p.evaluator(states,s)
                    result["cross_values"][key]=sum(prob*(vals[k] if kind=="C" else v) for kind,k,v,prob in selected.law)
            lane.reset()
            for suffix,(cont,search) in models.items():
                state,past=restore(lane,s,traces[arm],turn);seen=[]
                for step_turn,idx in traces[arm]:
                    if step_turn!=turn:continue
                    obs=host.project(state["observation"]);seen.append(json.loads(move(obs,obs["actions"][idx])))
                    past.append((obs,idx));state=step(lane,state,idx)
                result["actual"]=seen
                end=fight(lane,g2,s,suffix,cont,planner=search,resume=(state,past))
                result["suffix"][suffix]=dict(status=end["status"],hp=end["terminal"]["hp"],utility=utility(s|end))
                if suffix==arm:assert end["terminal"]==original[arm][i]["terminal"]
                lane.reset()
            by_arm[arm]=result
        case.update(turn=turn,hp=h["hp"],arms=by_arm)
    host.close();lane.close()
    (E/"flips.json").write_text(json.dumps(dict(cases=reports,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":run()
