"""Replay the deployed turn plus its predeclared continuation in the independent native game."""
import gzip,json,sys
from time import perf_counter
from panel5c import OUT,E
from complete import setup
from deploy5b import Lane,Search
from turn_worlds import source,prefix,restore,continue_high
from turn_native import replay
def run(tag):
    t=perf_counter()
    out=OUT/("native-"+tag)
    out.mkdir(parents=True,exist_ok=True)
    host,g2,net,plan=setup(out,"V2complete")
    lane=Lane(host,0)
    native=Lane(host,1)
    d=source(tag)
    past=prefix(lane,g2,net,d)
    st=restore(lane,d,past)
    g,ch,q=plan(lane,d["right"]["snapshot"]["h"],past,net,g2,d["spec"])
    assert q["use"] and q["conditional"]
    st,plays,reason=g["execute"](lane,st)
    assert reason in ("end","terminal")
    trace=past+plays
    st=continue_high(lane,st,trace,g2,net,Search(net,"high"),d["spec"])
    lane.reset()
    actual=replay(lane,native,d["spec"],trace)
    assert actual["hp"]==st["terminal_observation"]["hp"]
    assert actual["decision"] in (("card_reward","map_select") if st["status"]=="predicted_win" else ("game_over",))
    lane.close()
    native.close()
    host.close()
    (E/f"native-{tag}.json").write_text(json.dumps(dict(query=q,actual=actual,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":
    run(sys.argv[1])
