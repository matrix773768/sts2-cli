"""Compare the conditional replay against actual frozen G2, including selectors and draw observations."""
from produce import *
from play_loop import step,prepared
from collections import Counter
from semantic import encode
import numpy as np

def audit(out,n=30):
    out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    old,model=runtime(out);old.close();host=host_at(out,ROOT/"logs/core5a-host3")
    actual,shadow=Lane(host,0),Lane(host,1);counts=Counter();diffs=[]
    with gzip.open(FIVE/"evidence/panels.gz","rt") as f:jobs=json.load(f)["dev"][:n]
    for j in jobs:
        spec=j[1]|dict(seed=cohort.seed(j[3],"5a-audit",0))
        st=cohort.start(actual,spec);ss=cohort.start(shadow,spec)
        hist=[];route=[];actions=[];qualified=True;pred=None
        ctrl=prepared(model,host.project(st["observation"]),[]);ctrl.project=host.project
        while st["status"]=="active" and st["actions"]<128:
            h=host.project(st["observation"]);turn=h["turn"]
            a,_,_=ctrl.act(h,actual,st["actions"])
            if qualified:
                obs=pred if pred is not None else h
                rebuilt=prepared(model,obs,hist)
                guess=int(rebuilt.score([(obs,rebuilt.history)])[0][0].argmax())
                counts["actor_decisions"]+=1
                if obs!=h or a!=guess:
                    diffs.append([j[3],turn,"menu_or_action"]);qualified=False
                if h["decision"]["phase"]=="choice":counts["choice_decisions"]+=1
            hist.append((h,a));actions.append(a)
            st=step(actual,st,a);ctrl.after(st);pred=None
            if qualified:
                edge=dict(action=a,draws=[]);route.append(edge)
                draws=[e.split(":",2)[2] for e in st.get("pile_events",[]) if e.startswith("reveal:Hand:")]
                r=shadow.request("i1_core5_reference",route=route)["response"]
                while r["kind"]=="R" and draws and draws[0] in r["support"]:
                    edge["draws"].append(draws.pop(0));counts["observed_draws"]+=1
                    r=shadow.request("i1_core5_reference",route=route)["response"]
                k=r["kind"];counts[k]+=1
                if k=="decision":pred=host.project(r["state"])
                elif k=="C":
                    c=st.get("observed_c")
                    if c is None or not all(np.array_equal(x,y) for x,y in zip(encode(c),encode(r["state"]))):
                        diffs.append([j[3],turn,"C"])
                elif k in ("victory","death"):
                    if (k=="death")!=(st["status"]=="death") or r["state"]["hp"]!=st["terminal_observation"]["hp"]:
                        diffs.append([j[3],turn,"terminal"])
                else:qualified=False;counts[r.get("reason","unmatched_observation")]+=1
            if st["status"]=="active" and host.project(st["observation"])["turn"]!=turn:
                for idx in actions:ss=step(shadow,ss,idx)
                actions=[];route=[];pred=None;qualified=True
        actual.reset();shadow.reset()
    actual.close();shadow.close();host.close()
    result=dict(counts=counts,differences=diffs,seconds=time.perf_counter()-start)
    (out/"audit.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
if __name__=="__main__":audit(Path(sys.argv[1]))
