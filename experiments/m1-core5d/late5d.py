"""Bounded native route collection for later chapters, branching only at legal map saves."""
from progression5d import *
def run():
    start=perf_counter();out=OUT/"late";out.mkdir(parents=True,exist_ok=True)
    engine_client.headless_command=lambda:[str(ROOT/"logs/m0-v5/dotnet9/dotnet.exe"),"exec","--fx-version","9.0.7",str(ROOT/"logs/iik5-main-host/bin/Debug/net9.0/Sts2Headless.dll")]
    seeds=[]
    for variant in (0,1,2):
        data=load_asset(E/f"progression-{variant}.gz")
        r=next(x for x in data["roots"] if x["act"]==2)
        seeds.append((r["save"],[],variant,r["at"]))
    active=seeds;captured=[];attempts=0;failures={}
    for depth in range(25):
        next_nodes=[]
        for save,history,origin,index in active:
            for side in (0,1):
                attempts+=1
                g=engine_client.EngineClient(log_root=out)
                try:
                    s=g.send(dict(cmd="load_save",json=json.dumps(save)));moves=[];root=None
                    if s.get("decision")!="map_select":continue
                    menu=s["choices"];ordered=sorted(menu,key=lambda x:({"Ancient":0,"Treasure":1,"RestSite":2,"Shop":3,"Unknown":4,"Monster":5}.get(x["type"],6),x["col"]))
                    if side>=len(ordered):continue
                    node=ordered[side];cmd=action("select_map_node",col=node["col"],row=node["row"])
                    for k in range(130):
                        moves.append(cmd);s=g.send(cmd);d=s.get("decision")
                        if d=="map_select":
                            path=out/"map.save";assert g.send(dict(cmd="write_continue_save",path=str(path)))["success"]
                            dest=json.loads(path.read_bytes());hist=history+moves
                            next_nodes.append((dest,hist,origin,index))
                            break
                        if d=="combat_play" and root is None:
                            root=dict(act=s["context"]["act"],context=s["context"],player=s["player"],enemies=s["enemies"],
                                      save=save,origin=origin,origin_at=index,commands=history+moves[:])
                            if root["act"]>=3:captured.append(root)
                        if d=="game_over" or d is None:break
                        if d=="event_choice" and s.get("event_name")=="Slippery Bridge":cmd=action("choose_option",option_index=0)
                        else:cmd=choose(s,random.Random(421+depth),origin)
                except (ValueError,RuntimeError,KeyError,IndexError,TypeError,UnsupportedDecision,AssertionError) as err:
                    name=repr(err)[:140];failures[name]=failures.get(name,0)+1
                finally:g.close()
        if captured or not next_nodes:break
        def priority(n):
            s=n[0];p=s["players"][0]
            return s["current_act_index"],p["current_hp"],len(p["relics"]),p["gold"]
        active=sorted(next_nodes,key=priority,reverse=True)[:3]
    with gzip.open(E/"late-roots.gz","xt") as f:json.dump(dict(roots=captured,attempts=attempts,failures=failures,
        reached_act=max([2]+[r["act"] for r in captured]),seconds=perf_counter()-start),f)
def load_asset(path):
    with gzip.open(path) as f:return json.load(f)
if __name__=="__main__":run()
