"""Replay recorded Hot decisions in the frozen native game process, never in the policy path."""
import argparse
import ctypes
from ctypes import wintypes
from hot_produce import peak_rss
import gzip
import json
from pathlib import Path
import time
from client import ROOT,BUILD,launch


def native(out):
    import os
    folder=Path(os.environ.get("HOTSEARCH_ORACLE_DIR",BUILD/"oracle"))
    return launch(out/"native",folder/"bin/Release/net9.0/OfflineSearchHarness.dll")


def check(out,spec,r,intervention=None,meter=None):
    g=native(out)
    t=0
    order=None
    try:
        st=g.send(dict(cmd="synthetic_start",spec=spec));choices=r["choices"]
        def fail(why,**fields):
            return dict(status="diverged",step=t,reason=why,**fields)
        for t,(_,idx,kind,card,target,*side) in enumerate(r["trace"]):
            if st.get("decision")!="combat_play":return fail("native_phase",native=st.get("decision"),message=st.get("message"))
            b=r["boundaries"][t];p=st["player"]
            actual=(p["hp"],p["max_hp"],p["block"],st["energy"])
            expect=tuple(b[k] for k in ("hp","max_hp","block","energy"))
            if actual!=expect:return fail("resources",native=actual,hot=expect)
            hand=[(c["id"].split(".")[-1],int(c["upgraded"])) for c in st["hand"]]
            if hand!=list(map(tuple,b["hand"])):return fail("hand",native=hand,hot=b["hand"])
            actual=[(e["hp"],e.get("block",0)) for e in st["enemies"]]
            expect=[(x[1],x[2]) for x in b["foes"]]
            if actual!=expect:return fail("roster",native=actual,hot=expect)
            if intervention and t==intervention["at"]:
                verified=g.send(dict(cmd="resample",seed=intervention["seed"],counts=intervention["counts"]))
                if verified.get("type")!="resampled":return fail("native_resampling",reply=verified)
                order=verified["tokens"]
            args={} if card is None else dict(card_index=card)
            if target is not None:args["ally_index" if side==["ally"] else "target_index"]=target
            st=g.send(dict(cmd="action",action=kind,args=args))
            for c in (c for c in choices if c["at"]==t):
                if st.get("decision")!="card_select":return fail("choice_phase",native=st.get("decision"))
                if c["options"][c["selected"]]=="skip":
                    st=g.send(dict(cmd="action",action="skip_select"));continue
                cards=[x["id"].split(".")[-1]+"#"+str(int(x.get("upgraded",False))) for x in st["cards"]]
                options=[x for x in c["options"] if x!="skip"]
                if cards!=options:return fail("choice_menu",hot=options,native=cards)
                index=c["selected"]-c["options"][:c["selected"]].count("skip")
                st=g.send(dict(cmd="action",action="select_cards",args={"indices":str(index)}))
        decision=st.get("decision")
        if decision=="game_over":won=st.get("victory",False)
        elif decision in ("rewards","combat_rewards","card_reward","map_select","map"):won=True
        else:return fail("terminal_phase",native=decision,message=st.get("message"))
        p=st.get("player") or {}
        v=st.get("before_rewards") or p
        end={k:v.get(k) for k in ("hp","max_hp","gold")}
        equal=won==(r["status"]=="Victory") and all(end[k]==r["terminal"][k] for k in end)
        return dict(status="matched" if equal else "terminal_gap",step=len(r["trace"]),native=end,
                    hot={k:r["terminal"][k] for k in end},won=won,phase=decision,intervention_order=order)
    finally:
        try:
            if meter is not None:
                samples=[wintypes.FILETIME() for _ in range(4)]
                handle=int(g.proc._handle)
                if not ctypes.windll.kernel32.GetProcessTimes(ctypes.c_void_p(handle),*(ctypes.byref(s) for s in samples)):
                    raise ctypes.WinError()
                meter["cpu"]=sum(s.dwHighDateTime*2**32+s.dwLowDateTime for s in samples[2:])/1e7
                meter["peak_rss"]=peak_rss(handle)
        finally:g.close(graceful=False)


def run(out,source,ids,specs=None):
    out.mkdir(parents=True,exist_ok=False)
    panel=json.loads(specs.read_bytes()) if specs else json.load(gzip.open(ROOT/"experiments/m1-core5d/evidence/panel.gz"))["train"]
    start=time.perf_counter();cpu=time.process_time();costs=[]
    with (out/"results.jsonl").open("x",encoding="utf8") as stream:
        for r in map(json.loads,gzip.open(source)):
            if ids is not None and r["i"] not in ids:continue
            if not r.get("terminal"):
                stream.write(json.dumps(dict(i=r["i"],status="hot_incomplete",reason=r.get("reason")))+"\n");stream.flush()
                continue
            meter={};tick=time.perf_counter()
            try:result=check(out,panel[r["i"]]["spec"],r,meter=meter)
            except (KeyError,IndexError,ValueError,RuntimeError,TimeoutError) as e:result=dict(status="audit_error",reason=str(e).split("; phase=")[0][:500])
            meter["wall"]=time.perf_counter()-tick;costs.append(meter)
            result["cost"]=meter
            stream.write(json.dumps(dict(i=r["i"],encounter=r["encounter"],**result))+"\n");stream.flush()
    (out/"ledger.json").write_text(json.dumps(dict(wall=time.perf_counter()-start,python_cpu=time.process_time()-cpu,python_peak_rss=peak_rss(),
        host_cpu=sum(c.get("cpu",0) for c in costs),host_peak_rss=max((c.get("peak_rss",0) for c in costs),default=0),audited=len(costs))))
    (out/"seconds.json").write_text(json.dumps(time.perf_counter()-start))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("output",type=Path);p.add_argument("source",type=Path)
    p.add_argument("--ids",type=int,nargs="+");p.add_argument("--specs",type=Path);a=p.parse_args();run(a.output,a.source,a.ids,a.specs)
