"""Exercise generated cards, target choice and a real exhaust selector against the live episode."""
import json
from time import perf_counter
from panel5c import OUT,E
from complete import setup,PublicLane,move
from turn_worlds import source
from deploy5b import Lane
from play_loop import cohort,step
def run():
    t=perf_counter()
    out=OUT/"fixtures"
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,planner=setup(out,"V2complete")
    lane=Lane(host,0)
    public=PublicLane(lane)
    base=source("rescue")["spec"]
    data={}
    for cid,upgrade in (("INFERNAL_BLADE",1),("SWORD_BOOMERANG",0),("TRUE_GRIT",1)):
        s=base|dict(deck=[dict(id=cid,upgrade=upgrade)]+[dict(id=c,upgrade=0) for c in ["DEFEND_IRONCLAD","STRIKE_IRONCLAD"]*4])
        st=cohort.start(lane,s,list(range(len(s["deck"]))))
        h=host.project(st["observation"])
        a=next(x for x in h["actions"] if x["kind"]=="play_card" and h["hand"][x["card"]]["id"]==cid)
        def read(route):
            return public.request("i1_core5_reference",route=route)["response"]
        edge=dict(action=a["index"],draws=[])
        r=read([edge])
        branches=r.get("support",{})
        options=[]
        if r["kind"]=="R":
            for x,w in branches.items():
                response=read([dict(action=a["index"],draws=[x])])
                assert response["kind"]=="decision",response.get("reason")
                options.append((x,w/sum(branches.values()),host.project(response["state"])))
        else:
            assert r["kind"]=="decision",r
            options=[("",1.,host.project(r["state"]))]
        if cid=="TRUE_GRIT":
            menu=options[0][2]
            pick=next(x["index"] for x in menu["actions"] if x["kind"]=="select_candidate")
            picked_route=[edge,dict(action=pick,draws=[])]
            predicted_pick=host.project(read(picked_route)["state"])
            confirm=next(x["index"] for x in predicted_pick["actions"] if x["kind"]=="confirm_selection")
            predicted_exhaust=host.project(read(picked_route+[dict(action=confirm,draws=[])])["state"])
        st=step(lane,st,a["index"])
        actual=host.project(st["observation"])
        matches=[name for name,p,o in options if o==actual]
        assert matches
        result=dict(opening=h,first=move(h,a),outcomes=[dict(event=x,p=p,hand=[c["id"] for c in obs["hand"]],energy=obs["energy"]) for x,p,obs in options],matched=matches)
        if cid=="TRUE_GRIT":
            assert actual["decision"]["phase"]=="choice"
            idx=next(x["index"] for x in actual["actions"] if x["kind"]=="select_candidate")
            st=step(lane,st,idx)
            picked=host.project(st["observation"])
            assert picked==predicted_pick
            idx=next(x["index"] for x in picked["actions"] if x["kind"]=="confirm_selection")
            st=step(lane,st,idx)
            result["exhaust"]=host.project(st["observation"])["exhaust"]
            assert host.project(st["observation"])==predicted_exhaust
            assert len(result["exhaust"])==1
        data[cid]=result
        lane.reset()
    lane.close()
    host.close()
    (E/"mechanisms.json").write_text(json.dumps(dict(cases=data,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":
    run()
