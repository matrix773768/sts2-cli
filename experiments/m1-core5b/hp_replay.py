"""Execute the observed 999 HP actions on original HP, rebinding against the live legal menu."""
from deploy5b import *
from play_loop import step,cohort
from search import binding

def run_replay():
    out=LOGS/"5b-hp-replay";out.mkdir(exist_ok=False);t=perf_counter()
    host,g2,net,plan=init(out,"high");lane=Lane(host,0);res=[]
    for w in json.load(gzip.open(E/"panel.gz","rt"))["high"]:
        spec=w["spec"]
        s=cohort.start(lane,spec);h=host.project(s["observation"]);lane.reset()
        boosted=spec|dict(hp=999,max_hp=999)
        s=cohort.start(lane,boosted);b=host.project(s["observation"]);lane.reset()
        row=dict(family=w["family"],seed=spec["seed"],hard=w["hard"],same_hand=h["hand"]==b["hand"],same_enemies=h["enemies"]==b["enemies"])
        if w["hard"]:
            trace=[];r=fight(lane,g2,boosted,"high",net,planner=plan,trace=trace);lane.reset()
            if r["status"]=="predicted_win":
                s=cohort.start(lane,spec);reason="route_ended"
                for obs,idx in trace:
                    if s["status"]!="active":break
                    live=host.project(s["observation"]);a=obs["actions"][idx]
                    # Match marked target, card instance at that slot, and pending public selection.
                    if live["turn"]!=obs["turn"] or live["hand"]!=obs["hand"] or live["decision"]!=obs["decision"]:
                        reason="public_menu_changed";break
                    hit=next((v for v in live["actions"] if binding(live,v)==binding(obs,a)),None)
                    if hit is None:reason="illegal_after_hp_change";break
                    s=step(lane,s,hit["index"])
                row.update(replay=s["status"],reason=reason,actions=s["actions"],terminal=s.get("terminal_observation"));lane.reset()
        res.append(row)
    lane.close();host.close()
    (E/"hp-replay.json").write_text(json.dumps(dict(rows=res,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":run_replay()
