"""Execute the primary alternative lines on the original game host and verify the locked outcome."""
from turn_worlds import *

def replay(pred,live_lane,spec,trace):
    pred_state=cohort.start(pred,spec)
    live_lane.open();live=live_lane.request("synthetic_start",spec=spec)
    live_lane.request("i1_begin");selected=[];steps=[]
    for h,idx in trace:
        assert pred.host.project(pred_state["observation"])==h
        a=h["actions"][idx];kind=a["kind"];args={}
        if h["decision"]["phase"]=="choice":
            assert live["decision"]=="card_select"
            assert [(x["id"],x["upgrade"]) for x in h["decision"]["candidates"]]==[
                (x["id"].split(".")[-1],int(x["upgraded"])) for x in live["cards"]]
        else:
            assert live["decision"]=="combat_play"
            assert [x["id"] for x in h["hand"]]==[x["id"].split(".")[-1] for x in live["hand"]]
            assert h["energy"]==live["energy"]
        if kind=="select_candidate":selected.append(a["choice"])
        else:
            if kind=="confirm_selection":kind="select_cards";args["indices"]=",".join(map(str,selected));selected.clear()
            if kind=="play_card":
                args["card_index"]=a["card"]
                if a["target"] is not None:
                    side=a["target_side"];rp=pred.request("i1_iid_prediction_roster");rn=live_lane.request("i1_iid_native_roster")
                    args["ally_index" if side=="ally" else "target_index"]=rn[side].index(rp[side][a["target"]])
            live=live_lane.request("action",action=kind,args=args);steps.append((kind,args))
        pred_state=step(pred,pred_state,idx)
    f=live_lane.request("i1_iib_native_stamp");lock=f["state"][0]
    return dict(actions=steps,decision=live["decision"],terminal=f["terminal"],hp=lock["player_hp"],exact_hash=sha256(lock["exact_continuation_state"].encode()).hexdigest())

def run(tag):
    start=perf_counter();d=source(tag);probe=json.load(gzip.open(E/f"turn-probe-{tag}.gz"))
    km={k:model_key(c) for k,c in probe["states"].items() if c.get("schema")=="sts2.core.c.v3"}
    values={km[k]:v for k,v in probe["values"].items() if k in km}
    for r in probe["lines"].values():r["keys"]={km[k] for k in r["dist"] if k in km}
    out=LOGS/f"5b-turn-native-{tag}";out.mkdir(exist_ok=True)
    host,g2,v2,plan=init(out,"high");pred=Lane(host,0);native=Lane(host,1);past=prefix(pred,g2,v2,d);rows={}
    for name in (("defend2","adaptive_v2") if tag=="rescue" else ("head_combo","adaptive_v2","trance_static")):
        trace=[];r=trial(pred,d,past,probe,name,None,g2,v2,plan,values,trace);pred.reset()
        try:
            checked=replay(pred,native,d["spec"],trace);win=r["status"]=="predicted_win"
            checked["matches"]=(checked["hp"]==r["terminal"]["hp"] and
              (checked["terminal"] and checked["decision"] in ("card_reward","map_select") if win else checked["decision"]=="game_over"))
        except (AssertionError,KeyError,RuntimeError,IndexError) as e:checked=dict(matches=False,reason=repr(e))
        finally:pred.close();native.close()
        rows[name]=checked
    host.close();(E/f"turn-native-{tag}.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-start),indent=2))
if __name__=="__main__":run(sys.argv[1])
