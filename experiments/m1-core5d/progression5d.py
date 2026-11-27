"""Collect legal chapter-conditioned run prefixes, keeping acquisition effects and real resources."""
import gzip,json,random,sys
from time import perf_counter
from panel5d import ROOT,E,OUT
sys.path[:0]=[str(ROOT/"python"),str(ROOT/"tests")]
import engine_client
from run_route_smoke import choose_action,UnsupportedDecision,action
def choose(s,rng,variant):
    d=s["decision"]
    if d=="event_choice" and s.get("context",{}).get("act",1)>1:
        options=[o for o in s["options"] if not o.get("is_locked") and o.get("is_enabled",True)]
        if options:return action("choose_option",option_index=options[variant%len(options)]["index"])
    if d=="combat_play":
        enemies=[e for e in s["enemies"] if e["hp"]>0]
        incoming=sum((i.get("damage") or 0)*(i.get("hits") or 1) for e in enemies for i in e["intents"])
        need=max(0,incoming-s["player"]["block"])
        options=[]
        for c in s["hand"]:
            if not c["can_play"] or c["cost"]>s["energy"]:continue
            stats=c.get("stats") or {};block=stats.get("block") or 0
            variants=c.get("damage_by_target") or []
            targets=enemies if c["target_type"]=="AnyEnemy" else [None]
            if c["target_type"] not in ("AnyEnemy","RandomEnemy","AllEnemies","Self","None","TargetedNoCreature"):continue
            for e in targets:
                damage=next((v["damage"] for v in variants if e and v.get("damage") is not None and v["target_index"]==e["index"]),stats.get("damage") or 0)
                damage*=stats.get("hits") or 1
                score=damage+(1.2+.3*(variant%3))*min(block,need)
                if e and damage>=e["hp"]+e["block"]:score+=22
                if c["type"]=="Power":score+=12/max(1,s.get("round",1))
                if c["type"]=="Skill" and not block and not damage:score+=3
                score=(score+.1)/(max(1,c["cost"]))+.3*(c["cost"]==0)
                args=dict(card_index=c["index"])
                if e:args["target_index"]=e["index"]
                options.append((score,action("play_card",**args)))
        if options:return max(options,key=lambda x:x[0])[1]
    if d=="card_reward" and s.get("can_skip") and s["player"]["deck_size"]>19:return action("skip_card_reward")
    return choose_action(s,rng)[0]
def collect_action(s,rng,variant):
    d=s["decision"];p=s["player"]
    if d=="combat_play" and (p["hp"]<p["max_hp"]*.65 or s["context"].get("room_type") in ("Elite","Boss")):
        for potion in p["potions"]:
            if potion and potion.get("target_type") in ("AnyEnemy","AnyPlayer","Self","AllEnemies","TargetedNoCreature") and potion["name"]!="Fairy in a Bottle":
                args=dict(potion_index=potion["index"])
                if potion["target_type"]=="AnyEnemy":
                    args["target_index"]=min((e for e in s["enemies"] if e["hp"]>0),key=lambda e:e["hp"])["index"]
                return action("use_potion",**args)
    if d=="shop":
        stocked=[r for r in s["relics"] if r["is_stocked"] and r["cost"]<=p["gold"]]
        if stocked:return action("buy_relic",relic_index=min(stocked,key=lambda r:r["cost"])["index"])
    if d=="map_select":
        order=["Ancient","Treasure","RestSite","Shop","Unknown","Monster","Elite","Boss"]
        choices=s["choices"]
        if rng.random()<.75:
            best=min(choices,key=lambda x:order.index(x["type"]) if x["type"] in order else len(order))
            return action("select_map_node",col=best["col"],row=best["row"])
    return choose(s,rng,variant)

def run(variant,fresh=False,retry=False):
    tag=("recovered" if retry else "run" if fresh else "progression")+f"-{variant}"
    t=perf_counter();out=OUT/tag;out.mkdir(parents=True,exist_ok=True)
    engine_client.headless_command=lambda:[str(ROOT/"logs/m0-v5/dotnet9/dotnet.exe"),"exec","--fx-version","9.0.7",
                                            str(ROOT/"logs/iik5-main-host/bin/Debug/net9.0/Sts2Headless.dll")]
    g=engine_client.EngineClient(log_root=out)
    rng=random.Random(900+variant);witness=[];roots=[];events=[];saved=None;seen=set()
    route=list(map(json.loads,(ROOT/"tests/boss_reward_run_1.jsonl").read_text().splitlines()))
    if fresh:route=[dict(cmd="start_run",character="Ironclad",ascension=0,lang="en",seed=f"CORE5D-RELIC-{variant}")]
    stop=None
    try:
        for i in range(1200):
            if i<len(route):cmd=route[i]
            elif fresh:cmd=collect_action(s,rng,variant)
            elif i==len(route):
                idx=next(c["index"] for c in s["cards"] if c["name"]=="Offering")
                cmd=action("select_card_reward",card_index=idx)
            else:cmd=choose(s,rng,variant)
            if i and s["decision"]=="map_select":
                path=out/"boundary.save"
                response=g.send(dict(cmd="write_continue_save",path=str(path)))
                if not response.get("success"):raise ValueError(response)
                saved=json.loads(path.read_bytes())
            if i and s["decision"]=="event_choice":
                events.append(dict(at=i,name=s.get("event_name"),act=s["context"]["act"],
                    options=s["options"],command=cmd))
            s=g.send(cmd)
            if s.get("type")!="decision":stop=s;break
            witness.append(cmd);ctx=s["context"];key=(ctx["act"],ctx["floor"])
            if s["decision"]=="combat_play" and key not in seen:
                seen.add(key);p=s["player"]
                roots.append(dict(act=key[0],floor=key[1],at=i,context=ctx,hp=p["hp"],max_hp=p["max_hp"],gold=p["gold"],
                    relics=p["relics"],potions=p["potions"],deck=p["deck"],enemies=s["enemies"],save=saved))
            if s["decision"]=="game_over":stop=s["decision"];break
    except (UnsupportedDecision,RuntimeError,IndexError,KeyError,ValueError,TypeError) as err:stop=repr(err)
    finally:g.close()
    with gzip.open(E/f"{tag}.gz","xt",compresslevel=6) as f:
        json.dump(dict(commands=witness,roots=roots,events=events,stop=stop,seconds=perf_counter()-t),f,separators=(",",":"))
if __name__=="__main__":
    if sys.argv[1]=="recover":
        for path in sorted(E.glob("run-*.gz")):
            with gzip.open(path) as f:stop=str(json.load(f)["stop"])
            if stop=="KeyError('damage')" or "targets a single enemy" in stop:
                run(int(path.stem.split("-")[1]),True,True)
    elif len(sys.argv)>2:
        for variant in range(int(sys.argv[1]),32,int(sys.argv[2])):run(variant,True)
    else:run(int(sys.argv[1]))
