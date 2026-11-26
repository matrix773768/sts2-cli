import argparse
from time import perf_counter
from search import Lane,ask,execute,host_at,integrate,policy,write

S="STRIKE_IRONCLAD"
D="DEFEND_IRONCLAD"


def cases():
    yield "basic",[S,S,S,D,D],[],{},40
    yield "multi_target",[S,S,S,D,D],[],{},40
    yield "upgrade",[S,S+"+",D,D+"+",D],[],{},40
    yield "strength",["INFLAME",S,S,D,D],[],{},40
    yield "dexterity",["FOOTWORK","DEFEND_SILENT","DEFEND_SILENT","STRIKE_SILENT","STRIKE_SILENT"],[],{},40
    yield "vulnerable",["BASH",S,S,D,D],[],{},40
    yield "nunchaku",[S,S,S,D,D],[],dict(relic="NUNCHAKU",counter=9),40
    yield "fork",[D,D,D,S,S],[],dict(relic="TUNING_FORK",counter=9),40
    yield "draw",["POMMEL_STRIKE",D,D,D,D],[S,"BLUDGEON","BLUDGEON"],{},15
    yield "draw_reverse",["POMMEL_STRIKE",D,D,D,D],["BLUDGEON","BLUDGEON",S],{},15
    yield "lethal",[S,D,D,D,D],[],{},5


def run(out,build):
    out.mkdir(parents=True,exist_ok=False)
    host=host_at(out,build)
    rows={}
    t=perf_counter()
    for name,hand,tail,extra,hp in cases():
        lane=Lane(host,0)
        try:
            deck=[dict(id=c.rstrip("+"),upgrade=int(c.endswith("+"))) for c in hand+tail]
            spec=dict(schema=2,character="Silent" if name=="dexterity" else "Ironclad",ascension=0,act=1,act_variant="OVERGROWTH",
                 encounter="OVERGROWTH_CRAWLERS" if name=="multi_target" else "FUZZY_WURM_CRAWLER_WEAK",
                 seed="CORE1RFIX",hp=80,max_hp=80,
                 deck=deck,relics=[extra["relic"]] if extra else [],potions=[])
            lane.open()
            fx=dict(n4_order=list(range(len(deck))))
            if name!="multi_target": fx["enemy_hp"]=hp
            if extra: fx["relic_count"]=extra["counter"]
            st=lane.request("pre0_start",spec=spec,cap=128,sv1_fixture=fx)["episode"]
            h=host.project(st["observation"])
            graphs={mode:ask(lane,h,[],mode,1000) for mode in ("tree","no_dominance","reduced")}
            plan=policy(graphs["reduced"])
            settlement=integrate(lane,h,[],plan,96 if name=="basic" else 8)
            history=[]
            end,stop=execute(lane,st,history,graphs["reduced"],plan)
            rows[name]=dict(graphs=graphs,settlement=settlement,stop=stop,history=history,
                            after=host.project(end["observation"]) if end["status"]=="active" else end.get("terminal_observation"))
            print(name,stop,[(k,v["calls"],v["counts"]) for k,v in graphs.items()],flush=True)
        except (RuntimeError,ValueError,KeyError) as e:
            rows[name]=dict(error=str(e))
            print(name,str(e),flush=True)
        finally:
            lane.close()
            write(out/"fixtures.json.gz",dict(rows=rows,seconds=perf_counter()-t))
    host.close()
    if any("error" in row for row in rows.values()):
        raise RuntimeError("Fixture failures recorded in fixtures.json.gz")


if __name__=="__main__":
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("build",type=Path)
    a=p.parse_args()
    run(a.out,a.build.resolve())
