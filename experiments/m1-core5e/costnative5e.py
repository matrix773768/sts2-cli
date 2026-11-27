"""Serial same-root cost trials followed by separate independent native action replays."""
import gzip,json
from time import perf_counter
from panel5e import E,OUT,load,rows
from battle5e import setup_arm
from deploy5b import Lane,fight
from turn_native import replay
def run():
    name=json.loads((E/"selection.json").read_bytes())["challenger"]
    panel=load(E/"panel.gz")["confirm"];traces={};records={}
    arms=("V2",name)
    for arm in arms:
        start=perf_counter();tag=f"cost-{arm}-0";out=OUT/tag;out.mkdir(parents=True,exist_ok=True)
        host,g2,net,plan=setup_arm(out,arm);lane=Lane(host,0)
        official={r["i"]:r for f in E.glob("confirm-"+arm+"-*.gz") for r in rows(f)}
        records[arm]=official
        with gzip.open(E/(tag+".gz"),"xt") as f:
            for i in range(16):
                idx=8*i+i%2;w=panel[idx];s=w["spec"];trace=[];t=perf_counter();last={}
                try:
                    r=fight(lane,g2,s,arm,net,planner=plan,trace=trace,last=last);r.pop("states");lane.reset()
                except (KeyError,RuntimeError,IndexError,ValueError) as exc:
                    lane.close();r=dict(status="error",error=repr(exc),terminal=None,queries=[])
                assert r["terminal"]==official[idx]["terminal"] and r["status"]==official[idx]["status"]
                r.update(i=idx,family=w["family"],seed=s["seed"],hp=s["hp"],max_hp=s["max_hp"],turns=last.get("turn"),
                         arm=arm,seconds=perf_counter()-t)
                f.write(json.dumps(r)+"\n");traces[arm,idx]=trace,r
        lane.close();host.close();(E/(tag+".time.json")).write_text(json.dumps(perf_counter()-start))
    t=perf_counter();out=OUT/"native";out.mkdir(parents=True,exist_ok=True)
    flips=[i for i,r in records["V2"].items() if r["terminal"] and records[name][i]["terminal"]
           and r["status"]!=records[name][i]["status"]]
    for arm in arms:
        host,g2,net,plan=setup_arm(out,arm);lane=Lane(host,0)
        for i in flips:
            if (arm,i) in traces:continue
            trace=[];r=fight(lane,g2,panel[i]["spec"],arm,net,trace=trace,planner=plan)
            assert r["terminal"]==records[arm][i]["terminal"]
            traces[arm,i]=trace,r;lane.reset()
        lane.close();host.close()
    host,*_=setup_arm(out,"V2");sim=Lane(host,0);native=Lane(host,1)
    with gzip.open(E/"native.gz","xt") as f:
        for (arm,idx),(trace,r) in traces.items():
            check=dict(i=idx,arm=arm,flip=idx in flips,cost_root=idx in [8*i+i%2 for i in range(16)],
                       expected=r["status"],expected_hp=(r["terminal"] or {}).get("hp"))
            if r["terminal"]:
                try:
                    actual=replay(sim,native,panel[idx]["spec"],trace)
                    ended=(actual["terminal"] and actual["decision"] in ("card_reward","map_select")
                           if r["status"]=="predicted_win" else actual["decision"]=="game_over")
                    check.update(actual=actual,match=bool(actual["hp"]==r["terminal"]["hp"] and ended))
                except (AssertionError,RuntimeError,KeyError,IndexError,ValueError) as exc:
                    check.update(match=False,reason=repr(exc))
                finally:sim.close();native.close()
            f.write(json.dumps(check)+"\n")
    host.close();(E/"native.time.json").write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":run()
