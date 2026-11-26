"""Intervene on visible legal cards and observe two real EndTurn transitions."""
from state import *
from search import Lane,host_at,step,write
from time import perf_counter

def run(out,build):
    out.mkdir(parents=True,exist_ok=False)
    host=host_at(out,build.resolve())
    rows={}
    start=perf_counter()
    for name,plays in [("persistent",["INFLAME"]),("growth",["DEMON_FORM"]),
                       ("disarm",["MANGLE"]),("control",[]),("headbutt",["STRIKE_IRONCLAD","HEADBUTT"]),
                       ("strike",["STRIKE_IRONCLAD"]),("threshold",["STRIKE_IRONCLAD"])]:
        lane=Lane(host,0)
        try:
            hand=["STRIKE_IRONCLAD","STRIKE_IRONCLAD","HEADBUTT","DEFEND_IRONCLAD","INFLAME"]
            if name in ("growth","disarm","control"):hand=["STRIKE_IRONCLAD","STRIKE_IRONCLAD","DEMON_FORM","MANGLE","DEFEND_IRONCLAD"]
            deck=hand+["DEFEND_IRONCLAD"]*5
            spec=dict(schema=2,character="Ironclad",ascension=0,act=1,act_variant="OVERGROWTH",
                encounter="FUZZY_WURM_CRAWLER_WEAK",seed="CORE2",hp=80,max_hp=80,
                deck=[dict(id=c,upgrade=int(c=="INFLAME")) for c in deck],relics=["NUNCHAKU"] if name=="threshold" else [],potions=[])
            lane.open()
            fx=dict(n4_order=list(range(len(deck))),enemy_hp=80)
            if name=="threshold":fx["relic_count"]=9
            st=lane.request("pre0_start",spec=spec,cap=128,sv1_fixture=fx)["episode"]
            trace=[]
            if name=="control":
                cost=lane.request("i1_core1r2",mode="cost_fixture",budget=5)
                rows["cost"]={k:cost[k] for k in ("before","after")}
            for desired in plays+[None,None,None]:
                o=st["observation"]
                a=next(a for a in o["actions"] if (a["kind"]=="end_turn" if desired is None else
                        a["kind"]=="play_card" and o["hand"][a["card"]]["id"]==desired))
                st=step(lane,st,a["index"])
                while st["status"]=="active" and st["observation"]["decision"]["phase"]!="combat":
                    menus=st["observation"]["actions"]
                    act=next((m for m in menus if m["kind"]=="confirm_selection"),menus[0])
                    st=step(lane,st,act["index"])
                trace.append(dict(action=desired or "end",B=st.get("observation"),C=st.get("observed_c"),belief=st.get("public_law")))
            rows[name]=trace
        finally:lane.close()
    host.close()
    write(out/"diagnostics.json.gz",dict(rows=rows,seconds=perf_counter()-start))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
