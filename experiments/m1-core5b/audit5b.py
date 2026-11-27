"""Match newly expanded branches to public observations of live G2 on separate lanes."""
from deploy5b import *
from play_loop import prepared,cohort,step
from semantic import encode,np
from collections import Counter,deque
def audit():
    out=LOGS/"5b-audit-fixed";out.mkdir(exist_ok=False);t=perf_counter()
    host,model,_,_=init(out,"base");live,shadow=Lane(host,0),Lane(host,1)
    counts=Counter();mismatches=[]
    for w in json.load(gzip.open(E/"panel.gz","rt"))["historical"][::9]:
        spec=w["spec"];st=cohort.start(live,spec);ss=cohort.start(shadow,spec)
        h=host.project(st["observation"]);ctrl=prepared(model,h,[]);ctrl.project=host.project
        route=[];past=[];active=True
        while st["status"]=="active" and st["actions"]<128:
            h=host.project(st["observation"]);a,_,_=ctrl.act(h,live,st["actions"]);past.append(a)
            st=step(live,st,a);ctrl.after(st)
            target=host.project(st["observation"]) if st["status"]=="active" else None
            if active:
                pending=deque([[]]);matches=[];unknown=False;probes=0
                while pending and probes<64:
                    prefix=pending.popleft();edge=dict(action=a,draws=prefix);probes+=1
                    r=shadow.request("i1_core5_reference",route=route+[edge])["response"]
                    k=r["kind"]
                    if k=="R":
                        pending.extend(prefix+[x] for x in r["support"])
                    elif k=="decision" and target and host.project(r["state"])==target:matches.append((edge,k))
                    elif k=="C" and st.get("observed_c") and all(np.array_equal(x,y) for x,y in zip(encode(r["state"]),encode(st["observed_c"]))):matches.append((edge,k))
                    elif k in ("victory","death") and st["status"]==("death" if k=="death" else "predicted_win") and r["state"]["hp"]==st["terminal_observation"]["hp"]:matches.append((edge,k))
                    elif k=="unresolved":unknown=True
                if matches:
                    edge,k=matches[0];counts[k]+=1
                    for x in edge["draws"]:counts["event_"+("enemy" if x.startswith("move:") else "target" if x.startswith(("target","autoTarget")) else "hand" if x.startswith("hand") else "draw")]+=1
                    route.append(edge);active=len(matches)==1
                    if not active:counts["ambiguous"]+=1
                elif pending or unknown:active=False;counts["unverified"]+=1
                else:
                    mismatches.append(dict(family=w["family"],turn=h["turn"],action=a));active=False
            if target and target["turn"]!=h["turn"]:
                shadow.request("i1_core5_reference",clear=True)
                for idx in past:ss=step(shadow,ss,idx)
                past=[];route=[];active=True
        shadow.request("i1_core5_reference",clear=True);live.reset();shadow.reset()
    live.close();shadow.close();host.close()
    (E/"audit.json").write_text(json.dumps(dict(counts=counts,differences=mismatches,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":audit()
