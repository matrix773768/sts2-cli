"""Instrumentation only at existing CORE-5E callbacks. Private diagnostics never feed the policy."""
import json
import os
from time import perf_counter_ns as clock
import sys
from world_assets import CODE,OPEN,ROOT
from semantic_check import digest

def produce(task,folder,battle,pairs,meter,events,finish,on_record,observer=None):
    mode=task["mode"]; audit=task["kind"]=="audit"
    os.environ.update(STS2_CORE5E_RUN=str(folder),STS2_CORE5E_WORLD=str(ROOT/"logs"/
        ("core5e-world-host" if mode=="baseline" else "infra0-world-profile")))
    if task.get("variant"):
        if task["variant"].startswith("h-"):
            from integration import select_host
        else:
            from execution import select_host
        select_host(task,world=True)
    sys.path.insert(0,str(CODE))
    import conditions5e as c
    if audit:
        import data5e
        data5e.E=OPEN  # Followup scans the original complete training population.
    hooks=[]
    if events is not None:
        menu=c.menu
        def witness(*a,**kw):
            opts,states,main,q=menu(*a,**kw)
            events.append(["menu",digest([(o.first,o.label,o.value,o.law) for o in opts]),digest(states),main])
            return opts,states,main,q
        c.menu=witness
        actual=pairs.fight
        def terminal(*a,**kw):
            r=actual(*a,**kw)
            events.append(["suffix",digest([r["states"],r["terminal"],r["queries"]])])
            return r
        pairs.fight=terminal
    side=None
    if meter:
        c.rows=pairs.rows
        c.gzip=pairs.gzip
        c.json=pairs.json
        # c.restore/realize/menu/pair were imported from their defining modules.
        for name in ("choose_root","menu","pair","natural_rows","followup"):
            meter.wrap(c,name,"conditions/"+name)
        selected_pair=c.pair
        def pair_with_witness(*a,**kw):
            selected=selected_pair(*a,**kw)
            for opt in selected or []:
                original=opt.execute
                def execute(*args,fn=original):
                    return meter.timed("conditions/initial_execute",fn,*args)
                opt.execute=execute
            return selected
        c.pair=pair_with_witness
        host_at=c.host_at
        def bind(*args):
            host=host_at(*args)
            meter.wrap(host,"project","world_host/project")
            return host
        c.host_at=bind
        fight=pairs.fight
        inference_keys=tuple(f"{name}/{field}" for name in
            ("G2/encode","G2/forward","V2/encode","V2/forward") for field in ("n","ns"))
        def suffix(*a,**kw):
            before={k:meter.values[k] for k in inference_keys}
            start=clock()
            if side is not None:side["suffix_started"]=True
            try:r=fight(*a,**kw)
            finally:
                if side is not None:
                    side["suffix_wall_ns"]=clock()-start
                    side["suffix_inference"]={k:meter.values[k]-before[k] for k in inference_keys}
            if side is not None:
                side.update(suffix_decisions=r["actions"]-kw["resume"][0]["actions"],
                    suffix_queries=len(r["queries"]),suffix_sim_calls=sum(q["calls"] for q in r["queries"]),
                    suffix_turns=len(set(q["turn"] for q in r["queries"])),suffix_status=r["status"])
            return r
        pairs.fight=suffix
        restore=c.restore
        def restored(*a):
            st,past=restore(*a)
            if side is not None:side.update(prefix_actions=len(past),target_turn=a[3])
            return st,past
        c.restore=restored
    request=battle.Lane.request
    if meter or events is not None:
        def rpc(lane,cmd,**kw):
            if "diagnostic_world" not in kw:return request(lane,cmd,**kw)
            prefix=cmd
            vals=meter.values if meter else {}
            sent=vals.get("bytes_sent/"+prefix,0);recv=vals.get("bytes_received/"+prefix,0)
            start=clock()
            try:
                r=request(lane,cmd,**kw)
                response=r["response"]
                if side is not None:side["draw_count"]=sum(response["law"]["counts"].values())
                if events is not None:
                    events.append(["world",kw["diagnostic_world"],digest(lane.host.project(response["state"])),digest(response["law"])])
                return r
            finally:
                if side is not None:side.update(shuffle_ns=clock()-start,shuffle_calls=1,
                    shuffle_sent=vals.get("bytes_sent/"+prefix,0)-sent,shuffle_received=vals.get("bytes_received/"+prefix,0)-recv)
        battle.Lane.request=rpc

    fields=("world/start","conditions/initial_execute","pairs/restore","restore/replayed_action","option/program","search/program","conditions/menu","conditions/pair",
            "conditions/choose_root","lane/reset","pairs/realize","pairs/fight","plan/__call__","V2/forward","G2/forward","world_host/project")
    def snapshot():
        return {k:meter.values[k] for f in fields for k in (f+"/ns",f+"/n")}
    root_start=side_start=verify_start=0
    root_base=side_base=None
    root=None
    def end_side(now):
        nonlocal side
        current=snapshot()
        side.update(elapsed_ns=now-side_start,delta={k:v-side_base[k] for k,v in current.items() if v!=side_base[k]})
        root["sides"].append(side);side=None
    def phase(name,i,j,pos):
        nonlocal root,root_start,root_base,side,side_start,side_base,verify_start
        now=clock()
        if name=="root":
            root=dict(i=i,sides=[]);root_start=now;root_base=snapshot()
        elif name=="side":
            if not root["sides"]:
                root["fixed_ns"]=now-root_start
                root["fixed_counts"]={k:v-root_base[k] for k,v in snapshot().items() if v!=root_base[k]}
            side_start=now;side_base=snapshot();side=dict(world=j,side=pos)
        elif name=="verify":verify_start=now
        elif name=="execute":side["verify_ns"]=now-verify_start
        elif name=="side_end":end_side(now)
    def written(i):
        on_record(i)
        if meter:
            now=clock()
            if side is not None:end_side(now)
            root["root_ns"]=now-root_start
            if "fixed_ns" not in root:
                root["fixed_ns"]=root["root_ns"]
                root["fixed_counts"]={k:v-root_base[k] for k,v in snapshot().items() if v!=root_base[k]}
            hooks.append(root)
    callback=phase if meter else None
    if observer and hasattr(observer,"phase"):
        def callback(name,i,j,pos):
            observer.phase(name,i,j,pos)
            if meter:phase(name,i,j,pos)
    c.run("dev" if task["kind"]=="initial-dev" else "train",0,1,int(audit),indices=task["ids"],
        phase=callback,on_closed=finish,on_record=written)
    if meter:(folder/"world-stages.json").write_text(json.dumps(hooks))
