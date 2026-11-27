"""Inspect the one-turn rescue on the base policy's exact turn-five prefix."""
from review import *

def main():
    start=perf_counter()
    d=json.load(gzip.open(E/"review-long.gz"));spec=d["spec"];turn=5
    out=LOGS/"5b-fifth";out.mkdir(exist_ok=True)
    def battle(arm,force=False,j=None):
        host,g2,net,_=init(out,"base");lane=Lane(host,0);plan=Inspect(net,"base")
        plan.turn=turn;plan.swap=(turn,arm);plan.force=(turn,j) if force else None;trace=[]
        r=fight(lane,g2,spec,"base",net,planner=plan,trace=trace);lane.close();host.close()
        turns=defaultdict(list)
        for h,a in trace:turns[h["turn"]].append(description(h,a))
        return dict(row=r,turns=turns,snapshot=plan.snapshot)
    left=battle("base");right=battle("high");rival=next((p for p in right["snapshot"]["plans"][1:] if p["cov"]>=1-1e-9),None)
    alternatives=dict(reference=battle("high",True))
    if rival:alternatives["rival"]=battle("high",True,rival["j"])
    with gzip.open(E/"review-fifth.gz","wt") as f:json.dump(dict(tag="fifth",spec=spec,turn=turn,a="base",b="high",left=left,right=right,alternates=alternatives,oracle=None),f)
    (E/"fifth-cost.json").write_text(json.dumps(perf_counter()-start))
if __name__=="__main__":main()
