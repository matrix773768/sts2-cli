"""Recover the player's actual pending menu on the double-enemy review trajectory."""
from review import *

def main():
    t=perf_counter();d=json.load(gzip.open(E/"review-loss.gz"));out=LOGS/"5b-pending-review";out.mkdir(exist_ok=True)
    host,g2,net,plan=init(out,"base");lane=Lane(host,0);trace=[]
    r=fight(lane,g2,d["spec"],"base",net,planner=plan,trace=trace)
    lane.close();host.close()
    turn=[(h,i) for h,i in trace if h["turn"]==d["turn"]]
    assert [description(h,i) for h,i in turn]==d["left"]["turns"][str(d["turn"])]
    assert r["terminal"]==d["left"]["row"]["terminal"]
    rows=[dict(observation=h,action=h["actions"][i]) for h,i in turn if h["decision"]["phase"]!="combat"]
    (E/"pending-review.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":main()
