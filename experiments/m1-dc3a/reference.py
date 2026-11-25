"""Single-lane offline solver reference with cold root and route checks."""
import argparse
from collections import Counter
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-dc1"))
from dc_common import ROOT, checksum, config, digest, frozen, read, write_json
from loop_battle import Host

sys.path.insert(0,str(ROOT))
from tools.training_manager.worker import progress

BASE=ROOT/"logs/m1-dc1-formal/roots/development.json"
COMPLEX=ROOT/"logs/m1-dc2b-frozen/development.json"
BUILD=ROOT/"logs/m1-sv4a-host"
TIERS=((128,1),(512,10),(2048,60))
SOLVER="0.51.5-iik.3b + SV4A overlay"


def record(source,path,j):
    return dict(source=source,ordinal=j[0],spec=j[1],family=j[3],room=j[4],
                id=digest([source,*j]),manifest=checksum(path))


def freeze(out):
    import random
    pools={"fixed":BASE,"complex":COMPLEX}
    pilot,formal=[],[]
    for source,path in pools.items():
        jobs=read(path)["jobs"]
        groups={}
        held=set()
        for hp in (80,160,999):
            group=[j for j in jobs if j[1]["max_hp"]==hp]
            random.Random(digest(["dc3a",source,hp])).shuffle(group)
            groups[hp]=group
            eligible=[]
            for j in group:
                if j[3] not in held:
                    held.add(j[3])
                    eligible.append(j)
                    if len(eligible)==4:
                        break
            if len(eligible)!=4:
                raise ValueError("Pilot stratum not populated")
            pilot.extend(record(source,path,j) for j in eligible)
        for group in groups.values():
            main=[j for j in group if j[3] not in held][:32]
            if len(main)!=32:
                raise ValueError("Formal stratum not populated")
            formal.extend(record(source,path,j) for j in main)
    for name,data in (("pilot",pilot),("formal",formal)):
        frozen(out/f"{name}.json",dict(kind=f"dc3a-{name}",worlds=data))
    assert len({w["spec"]["seed"] for w in pilot+formal})==216


@contextmanager
def opened(host,world):
    lane=host.lane()
    try:
        start=perf_counter()
        lane.open()
        state=lane.request("pre0_start",spec=world["spec"],cap=256)["episode"]
        before=lane.request("synthetic_snapshot")
        identity=lane.request("f1_audit")
        yield lane,host.project(state["observation"]),before,identity,perf_counter()-start
    finally:
        host.close()


def witness(host,world,base,route):
    start=perf_counter()
    with opened(host,world) as (lane,public,snapshot,audit,_):
        if digest([public,snapshot,audit])!=base:
            return dict(status="root_mismatch")
        actions=route["actions"]
        if not actions or len(actions)>48:
            return dict(status="action_cap")
        kinds=("PlayCard","UsePotion","EndTurn")
        actions=[a|{"kind":kinds[a["kind"]]} if isinstance(a["kind"],int) else a for a in actions]
        fixed=lane.request("i1_capture",fixed_actions=actions)
        frames=fixed.get("frames",[])
        if fixed["status"]!="complete_win" or len(frames)!=len(actions):
            return dict(status="prediction_mismatch",replay=fixed["status"])
        import hashlib
        stamps=[hashlib.sha256(f[0]["exact_continuation_state"].encode()).hexdigest() for f in frames]
        if route.get("stamps") and stamps!=route["stamps"]:
            return dict(status="prediction_mismatch",reason="F3B continuation stamps differ")
        native=lane.request("i1_begin")["state"]
        if native!=fixed["root"]:
            return dict(status="native_mismatch",step=0)
        for i,(action,expected) in enumerate(zip(fixed["actions"],frames,strict=True),1):
            result=lane.request("i1_step",action=action)
            if result.get("state")!=expected or result.get("terminal")!=(i==len(actions)):
                return dict(status="native_mismatch",step=i,wire=result.get("type"))
        final=lane.request("f1_final")
        outcome=final.get("outcome") or {}
        hp=outcome.get("final_hp")
        if hp is None or hp<=0 or result["decision"]["decision"] not in ("card_reward","map_select"):
            return dict(status="unconfirmed_terminal",terminal=final)
        return dict(status="native_win",end_hp=hp,net=world["spec"]["hp"]-hp,
                    max_hp=final["resources"]["max_hp"],reported_hp_lost=outcome.get("hp_lost"),
                    healing=None,terminal=final,actions=actions,
                    length=len(actions),replay_seconds=perf_counter()-start,
                    frame_hashes=[digest(f) for f in frames])


def solve(host,world,tiers):
    incumbent=None
    rows=[]
    base=None
    surfaces=None
    for cap,wall in tiers:
        tick=None
        try:
            with opened(host,world) as (lane,public,snapshot,audit,init):
                key=digest([public,snapshot,audit])
                if base is not None and key!=base:
                    raise ValueError("Cold rebuild mismatch")
                base=key
                surfaces={"public":digest(public),"native":digest(snapshot),"audit":digest(audit)}
                tick=perf_counter()
                timeout=lane.client._command_timeout
                lane.client._command_timeout=wall
                try:
                    resp=lane.request("i1_f3b",arm="C",cap=cap,potions=False,rejected=[])
                finally:
                    lane.client._command_timeout=timeout
                seconds=perf_counter()-tick
                if lane.request("f1_audit")!=audit:
                    raise ValueError("Search mutated source")
            route=resp.get("search")
            if route and not 0<=route["transitions"]<=cap:
                raise ValueError("Transition cap mismatch")
            result=dict(cap=cap,wall_seconds=wall,search_seconds=seconds,init_seconds=init,
                        search_status=route["status"] if route else resp["status"],
                        transitions=route.get("transitions") if route else None)
            if route and route["status"]=="predicted_win":
                result["route"]=route
                result["first_win_rpc_seconds"]=seconds
                validation=witness(host,world,base,route)
                result["validation"]=validation
                if validation["status"]=="native_win" and (incumbent is None or validation["net"]<incumbent["net"]):
                    incumbent=validation | {"cap":cap}
            result["incumbent"]=incumbent
        except (RuntimeError,ValueError,KeyError,OSError,TimeoutError) as error:
            result=dict(cap=cap,wall_seconds=wall,search_status="timeout" if isinstance(error,TimeoutError) or "timeout" in str(error).lower() else "error",
                        detail=str(error),incumbent=incumbent,
                        elapsed_since_search_start=perf_counter()-tick if tick is not None else None)
        rows.append(result)
    return dict(world=world,reference=incumbent,tiers=rows,root=base,
                root_attestation=surfaces,solver=SOLVER,host=host.version,information="offline_oracle_full_rng")


def choose(rows):
    measured=[]
    for i in range(len(TIERS)):
        winners={r["world"]["id"]:r["tiers"][i]["incumbent"]["net"]
                 for r in rows if r["tiers"][i]["incumbent"]}
        measured.append(dict(index=i,winners=winners))
    final=measured[-1]["winners"]
    selection=next(m for m in measured if m["winners"].keys()==final.keys() and
                   sum(m["winners"].values())-sum(final.values())<=2*len(final))
    return dict(tiers=[list(t) for t in TIERS[:selection["index"]+1]],measured=measured,
                rule="full pilot cumulative coverage; mean loss within two HP of largest tier")


def run(out,manifest,limit,budget=None):
    data=read(manifest)
    if data["kind"] not in ("dc3a-pilot","dc3a-formal"):
        raise ValueError("Expected a DC3A development-only manifest")
    if data["kind"]=="dc3a-formal":
        picked=read(budget)
        tiers=tuple(tuple(t) for t in picked["tiers"])
        if tiers!=TIERS[:len(tiers)] or not tiers or picked["pilot_worlds"]!=24:
            raise ValueError("Expected frozen budget from the 24-world pilot")
    else:
        tiers=TIERS
    originals={name:(checksum(path),{j[0]:j for j in read(path)["jobs"]})
               for name,path in (("fixed",BASE),("complex",COMPLEX))}
    for world in data["worlds"]:
        source=world["source"]
        _, originals_by_index=originals[source]
        if world!=record(source,BASE if source=="fixed" else COMPLEX,originals_by_index[world["ordinal"]]):
            raise ValueError("World is outside the two admitted development queues")
    jobs=data["worlds"][:limit]
    with closing(sqlite3.connect(out/"reference.sqlite")) as db:
        db.executescript("CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY,payload TEXT);"
                         "CREATE TABLE IF NOT EXISTS contract(id TEXT PRIMARY KEY);")
        done={r[0] for r in db.execute("SELECT id FROM results")}
        identity=digest([checksum(manifest),limit,tiers,checksum(budget) if budget else None,checksum(Path(__file__)),checksum(BUILD/"build.json")])
        existing=db.execute("SELECT id FROM contract").fetchone()
        if existing and existing[0]!=identity:
            raise ValueError("Reference identity changed")
        with db:
            db.execute("INSERT OR IGNORE INTO contract VALUES (?)",(identity,))
        host=Host(out,BUILD,config()|{"workers":1})
        start=perf_counter()
        for world in jobs:
            if "INF1_PROGRESS" in os.environ:
                progress(len(done),len(jobs),(out/"reference.sqlite").resolve(),throughput=len(done)/max(.001,perf_counter()-start))
            if world["id"] in done:
                continue
            stop=os.getenv("INF1_STOP")
            if stop and Path(stop).exists():
                return 75
            row=solve(host,world,tiers)
            with db:
                db.execute("INSERT INTO results VALUES (?,?)",(world["id"],json.dumps(row)))
            done.add(world["id"])
            print(world["id"][:8],[(r["search_status"],r.get("validation",{}).get("status")) for r in row["tiers"]],flush=True)
        rows=[json.loads(raw) for raw, in db.execute("SELECT payload FROM results ORDER BY id")]
        selection=None
        if data["kind"]=="dc3a-pilot" and len(jobs)==24:
            if not any(r["reference"] for r in rows):
                write_json(out/"summary.json",dict(attempts=len(rows),native_wins=0,
                           status="no_native_reference",manifest=checksum(manifest)))
                raise ValueError("Pilot produced no native-verified reference; inspect failure evidence")
            selection=choose(rows)|dict(pilot_worlds=24,pilot_manifest=checksum(manifest))
            frozen(out/"budget.json",selection)
        write_json(out/"summary.json",dict(attempts=len(rows),native_wins=sum(bool(r["reference"]) for r in rows),
                   statuses={str(i):dict(Counter(r["tiers"][i]["search_status"] for r in rows))
                             for i in range(len(tiers))},
                   budget=tiers,selection=selection,manifest=checksum(manifest),database=checksum(out/"reference.sqlite")))
        if "INF1_PROGRESS" in os.environ:
            progress(len(done),len(jobs),(out/"reference.sqlite").resolve())
    return 0


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output",type=Path)
    cli.add_argument("--manifest",type=Path)
    cli.add_argument("--limit",type=int)
    cli.add_argument("--budget-file",type=Path)
    args=cli.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    if args.manifest:
        raise SystemExit(run(out,args.manifest,args.limit,args.budget_file))
    freeze(out)
