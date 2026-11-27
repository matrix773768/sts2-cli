"""Prepare indexed native roots with chapter/run-balanced weights and independently reload witnesses."""
import gzip,json
from collections import Counter,defaultdict
from time import perf_counter
from progression5d import ROOT,E,OUT,engine_client
from panel5d import load,digest
from state import static_rules

def collect():
    t=perf_counter();roots=[];seen=set();stops={};streams={}
    for file in sorted((*E.glob("progression-*.gz"),*E.glob("run-*.gz"))):
        source=load(file)
        retry=E/file.name.replace("run-","recovered-")
        if file.name.startswith("run-") and retry.exists():
            alt=load(retry)
            if len(alt["roots"])>=len(source["roots"]):file,source=retry,alt
        streams[file.name]=source;seed=source["commands"][0]["seed"];stops[file.name]=source["stop"]
        for idx,r in enumerate(source["roots"]):
            public={k:r[k] for k in ("act","floor","context","hp","max_hp","gold","deck","potions","relics","enemies")}
            key=digest([seed,public]);snap=r.get("save")
            if key in seen or not snap:continue
            seen.add(key)
            # The saved map position is immediately before this map action and may lead to a combat via an event.
            enter=max(i for i,cmd in enumerate(source["commands"][:r["at"]+1]) if cmd.get("action")=="select_map_node")
            roots.append(dict(key=key,file=file.name,index=idx,seed=seed,act=r["act"],floor=r["floor"],enter=enter,
                        at=r["at"],hp=r["hp"],max_hp=r["max_hp"],gold=r["gold"],cards=len(r["deck"]),
                        relics=[v["name"] for v in r["relics"]],potions=sum(bool(v) for v in r["potions"])))
    families=defaultdict(Counter)
    for z in roots:families[z["act"]][z["seed"]]+=1
    for z in roots:
        f=families[z["act"]];z["weight"]=1/(len(families)*len(f)*f[z["seed"]])
    assert abs(sum(z["weight"] for z in roots)-1)<1e-8
    out=OUT/"native-reload";out.mkdir(parents=True,exist_ok=True)
    engine_client.headless_command=lambda:[str(ROOT/"logs/m0-v5/dotnet9/dotnet.exe"),"exec","--fx-version","9.0.7",
                                             str(ROOT/"logs/iik5-main-host/bin/Debug/net9.0/Sts2Headless.dll")]
    replay=[]
    for act in sorted(families):
        root=max((z for z in roots if z["act"]==act),key=lambda z:z["floor"])
        source=streams[root["file"]];r=source["roots"][root["index"]]
        checks={}
        g=engine_client.EngineClient(log_root=out)
        try:
            s=g.send(dict(cmd="load_save",json=json.dumps(r["save"])))
            for cmd in source["commands"][root["enter"]:root["at"]+1]:s=g.send(cmd)
            checks["map_restore"]=s.get("decision")=="combat_play" and all(
                s["player"].get(k)==r[k] for k in ("hp","max_hp","gold","deck","relics","potions")) and s["enemies"]==r["enemies"]
        finally:g.close()
        if not checks["map_restore"]:
            g=engine_client.EngineClient(log_root=out)
            try:
                for cmd in source["commands"][:root["at"]+1]:s=g.send(cmd)
                checks["full_prefix"]=s.get("decision")=="combat_play" and all(
                    s["player"].get(k)==r[k] for k in ("hp","max_hp","gold","deck","relics","potions")) and s["enemies"]==r["enemies"]
            finally:g.close()
        replay.append(dict(key=root["key"],act=act,file=root["file"],**checks))
    ids={r["id"].split(".")[-1] for x in streams.values() for r0 in x["roots"] if r0["save"]
         for r in r0["save"]["players"][0]["relics"]}
    result=dict(roots=roots,stops=stops,replay=replay,counts={k:dict(roots=sum(v.values()),runs=len(v)) for k,v in families.items()},
        native_ids=sorted(ids),catalog_ids=sorted(ids & static_rules()["relics"].keys()),seconds=perf_counter()-t)
    (E/"relic-panel.json").write_text(json.dumps(result,indent=2))
if __name__=="__main__":collect()
