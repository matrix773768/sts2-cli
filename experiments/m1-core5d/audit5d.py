"""Replay directed low-budget policies, an order-equivalence fixture and a development host fault."""
import json
from collections import Counter
from time import perf_counter
from panel5d import E,OUT,cohort,load,rows
from battle5d import configure
from complete import PublicLane,Turn,host_at
from policy5c import can_group
from stress5c import Ordered
from turn_worlds import source,prefix,restore,model_key
from options5d import menu
from deploy5b import Lane,fight
from play_loop import step

def cases(lane,g2,net,plan):
    results={}
    for tag in ("loss","rescue"):
        d=source(tag)
        past=prefix(lane,g2,net,d)
        st=restore(lane,d,past)
        h=lane.host.project(st["observation"])
        opts,_,main,q=menu(lane,h,past,net,g2,d["spec"],plan)
        lane.reset()
        witnesses=[]
        for opt in opts:
            if not opt.label.startswith("conditional/"):continue
            idx=int(opt.label.split("/")[1])
            st=restore(lane,d,past)
            st,moves,reason=opt.execute(lane,st)
            c=st.get("observed_c")
            key=model_key(c) if c else None
            witnesses.append(dict(label=opt.label,first=h["hand"][h["actions"][idx]["card"]]["id"],
                value=opt.value,law=opt.law,steps=[(obs["decision"]["phase"],obs["actions"][i]) for obs,i in moves],
                reason=reason,matched_C=bool(key and any(z[1]==key for z in opt.law))))
            lane.reset()
        results[tag]=dict(main=main,query=q,witnesses=witnesses)
        lane.close()
    return results

def relic(lane,plan):
    names=["BATTLE_TRANCE","STRIKE_IRONCLAD","DEFEND_IRONCLAD","STRIKE_IRONCLAD","DEFEND_IRONCLAD",
           "DEFEND_IRONCLAD","STRIKE_IRONCLAD","BASH","STRIKE_IRONCLAD","DEFEND_IRONCLAD"]
    rejected=[]
    for world in load(E/"panel.gz")["train"][:60]:
        if world["spec"]["act"]>2:continue
        s=world["spec"]|dict(schema=2,deck=[dict(id=k,upgrade=0) for k in names],relics=["BURNING_BLOOD"])
        st=cohort.start(lane,s,list(range(len(names))))
        h=lane.host.project(st["observation"])
        a=next(x for x in h["actions"] if x["kind"]=="play_card" and h["hand"][x["card"]]["id"]==names[0])
        if not can_group(h,a):lane.reset();continue
        result={}
        for cls in (Ordered,Turn):
            t=cls(PublicLane(lane),h,s,plan.evaluator,128)
            t.cap=512;leaves=[]
            t.follow(h,a,(),"end",False,1.,(),leaves)
            law=Counter()
            for p,k,v,_ in leaves:
                key=(model_key(t.states[v]) if k=="C" else (str((k,t.values[v])) if v in t.values else k))
                law[key]+=p
            result[cls.__name__]=dict(law=law,requests=len(t.cache),grouped=t.merges,
                kinds=dict(Counter(k for _,k,_,_ in leaves)))
        if not result["Turn"]["grouped"] or result["Turn"]["kinds"].keys()!={"C"}:
            rejected.append([s["encounter"],result["Turn"]["grouped"],result["Turn"]["kinds"]])
            lane.reset();continue
        x=result["Turn"]["law"];y=result["Ordered"]["law"]
        assert x.keys()==y.keys() and all(abs(x[k]-y[k])<1e-8 for k in x)
        actual=step(lane,st,a["index"])
        after=lane.host.project(actual["observation"])
        end=next(x["index"] for x in after["actions"] if x["kind"]=="end_turn")
        observed=step(lane,actual,end)["observed_c"]
        assert model_key(observed) in x
        return dict(spec=s,projected=h["relics"],encoded_C_relics=observed["relics"],match=True,rejected=rejected,
            ordered_listener=not can_group(h|dict(relics=["NUNCHAKU"]),a),**result)
    raise ValueError(f"No commuting draw fixture found: {rejected}")

def main():
    start=perf_counter();out=OUT/"audits";out.mkdir(exist_ok=True,parents=True)
    host,g2,net,plan=configure(out,"V2low");lane=Lane(host,0)
    try:
        data=dict(cases=cases(lane,g2,net,plan),relic=relic(lane,plan))
    finally:lane.close();host.close()
    data["seconds"]=perf_counter()-start
    (E/"audit.json").write_text(json.dumps(data,indent=2))
if __name__=="__main__":main()
