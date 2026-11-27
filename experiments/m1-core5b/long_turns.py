from review import *
def sweep():
    t=perf_counter();d=json.load(gzip.open(E/"review-long.gz","rt"));spec=d["spec"]
    out=LOGS/"5b-long-sweep";out.mkdir(exist_ok=False)
    host,g2,net,_=init(out,"base");lane=Lane(host,0);plan=Inspect(net,"base");results=[]
    for q in d["left"]["row"]["queries"]:
        turn=q["turn"];plan.swap=(turn,"high");trace=[]
        r=fight(lane,g2,spec,"base",net,planner=plan,trace=trace);lane.reset()
        results.append(dict(turn=turn,status=r["status"],terminal=r["terminal"],actions=[description(h,a) for h,a in trace if h["turn"]==turn]))
    lane.close();host.close();(E/"long-turns.json").write_text(json.dumps(dict(rows=results,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":sweep()
