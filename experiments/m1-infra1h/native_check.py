"""Independently replay three predeclared natural trajectories on the unmodified native game."""
import gzip
import json
from pathlib import Path
import sys
import os
import traceback
from campaign import HERE,ROOT,E,LOG,RUNS

def run(tag):
    from time import perf_counter
    sys.path.insert(0,str(HERE.parent/"m1-core5d"))
    import battle5d
    from complete import host_at
    from panel5d import cohort
    from turn_native import replay
    worker=RUNS/tag/"worker-0"
    if not json.loads((worker/"verification.json").read_bytes())["equal"]:raise ValueError("Unverified production rows")
    meta=json.loads((worker/"worker.json").read_bytes())
    rows={r["i"]:r for r in map(json.loads,gzip.open(worker/"evidence"/meta["closed"]["file"]))}
    panel=json.load(gzip.open(HERE.parent/"m1-core5d/evidence/panel.gz"))["train"]
    ids=[min(rows),154,max(sorted(rows),key=lambda i:len(rows[i]["trace"]))]
    out=LOG/("native-"+tag+"-"+str(os.getpid()))
    out.mkdir()
    results=[]
    from collections import Counter
    for idx in dict.fromkeys(ids):
        start=perf_counter()
        item=rows[idx]
        spec=panel[idx]["spec"]
        for lane_name in ("pred","game"):(out/str(idx)/lane_name).mkdir(parents=True)
        host=host_at(out/str(idx)/"pred",ROOT/"logs/infra1h-5d-kernel3")
        real=host_at(out/str(idx)/"game",ROOT/"logs/core5c-host")
        pred,native=battle5d.Lane(host,0),battle5d.Lane(real,1)
        result=dict(i=idx,expected=item["terminal"],status=item["status"],trace_length=len(item["trace"]))
        try:
            st=cohort.start(pred,spec)
            path=[]
            for turn,a in item["trace"]:
                h=host.project(st["observation"])
                assert h["turn"]==turn
                path.append((h,a))
                st=cohort.step(pred,st,a)
            actual_prediction=st["terminal_observation"]|dict(gold=(st.get("result") or {}).get("gold"))
            assert st["status"]==item["status"] and actual_prediction==item["terminal"],actual_prediction
            pred.reset()
            result["kinds"]=dict(Counter(h["actions"][a]["kind"] for h,a in path))
            actual=replay(pred,native,spec,path)
            stamp=native.request("i1_iib_native_stamp")["state"][0]
            max_hp=stamp.get("player_max_hp")
            ok=actual["hp"]==item["terminal"]["hp"] and (max_hp is None or max_hp==item["terminal"]["max_hp"])
            if "player_gold" in stamp:ok=ok and stamp["player_gold"]==item["terminal"]["gold"]
            result["native_gold"]=stamp.get("player_gold")
            decision_ok=actual["decision"] in (("card_reward","map_select") if item["status"]=="predicted_win" else ("game_over",))
            result.update(actual=actual,native_max_hp=max_hp,matched=bool(ok and decision_ok))
        except (AssertionError,KeyError,IndexError,RuntimeError,ValueError) as e:
            result.update(matched=False,error=repr(e),frame=traceback.format_exc().splitlines()[-3:])
        finally:
            pred.close();native.close();host.close();real.close()
        result["seconds"]=perf_counter()-start
        results.append(result)
    (E/"native-natural.json").write_text(json.dumps(dict(source=tag,rows=results),indent=2))
    print([(r["i"],r["matched"]) for r in results])
if __name__=="__main__":run(sys.argv[1])
