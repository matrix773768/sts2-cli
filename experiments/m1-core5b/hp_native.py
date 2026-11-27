"""Cold replay the two high-HP transfers that survived at their original HP."""
from hp_replay import *
from hashlib import sha256

def main():
    t=perf_counter()
    out=LOGS/"5b-hp-native";out.mkdir(exist_ok=True)
    host,g2,net,plan=init(out,"high")
    pred,native=Lane(host,0),Lane(host,1)
    trials={r["family"]:r for r in json.loads((E/"hp-replay.json").read_bytes())["rows"] if r.get("replay")=="predicted_win"}
    result=[]
    for w in json.load(gzip.open(E/"panel.gz"))["high"]:
        if w["family"] not in trials:continue
        spec=w["spec"];trace=[];record=dict(family=w["family"],seed=spec["seed"],actions=[],frames=[])
        try:
            fight(pred,g2,spec|dict(hp=999,max_hp=999),"high",net,planner=plan,trace=trace);pred.reset()
            state=cohort.start(pred,spec);native.open()
            live=native.request("synthetic_start",spec=spec);native.request("i1_begin");selected=[]
            for h,idx in trace:
                if state["status"]!="active":break
                o=host.project(state["observation"]);act=h["actions"][idx]
                if o["hand"]!=h["hand"] or o["decision"]!=h["decision"]:raise ValueError("predicted menu changed")
                a=next(v for v in o["actions"] if binding(o,v)==binding(h,act));kind=a["kind"];args={}
                if kind=="select_candidate":selected.append(a["choice"])
                else:
                    if kind=="confirm_selection":
                        kind="select_cards";args=dict(indices=",".join(map(str,selected)));selected.clear()
                    if kind=="play_card":
                        args["card_index"]=a["card"]
                        if live["hand"][a["card"]]["id"].split(".")[-1]!=o["hand"][a["card"]]["id"]:raise ValueError("native hand changed")
                        if a.get("target") is not None:
                            side=a["target_side"];rp=pred.request("i1_iid_prediction_roster");rn=native.request("i1_iid_native_roster")
                            args["ally_index" if side=="ally" else "target_index"]=rn[side].index(rp[side][a["target"]])
                    live=native.request("action",action=kind,args=args)
                    record["actions"].append(dict(kind=kind,args=args))
                state=step(pred,state,a["index"])
                if state.get("audit_stamp"):
                    f=native.request("i1_iib_native_stamp")["state"][0]
                    record["frames"].append(dict(expected=state["audit_stamp"],native=sha256(f["exact_continuation_state"].encode()).hexdigest()))
            final=native.request("i1_iib_native_stamp")
            locked=final["state"][0]
            record.update(decision=live["decision"],locked=final["terminal"],end_hp=locked["player_hp"],
                          end_max_hp=locked["player_max_hp"],gold=locked["player_gold"],
                          terminal_hash=sha256(locked["exact_continuation_state"].encode()).hexdigest())
            ok=(final["terminal"] and live["decision"] in ("card_reward","map_select") and locked["player_hp"]==trials[w["family"]]["terminal"]["hp"])
            record["status"]="native_win" if ok else "native_mismatch"
        except (RuntimeError,KeyError,ValueError,IndexError) as e:record.update(status="unverified",reason=str(e))
        finally:pred.close();native.close()
        result.append(record)
    host.close()
    (E/"hp-native.json").write_text(json.dumps(dict(rows=result,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":main()
