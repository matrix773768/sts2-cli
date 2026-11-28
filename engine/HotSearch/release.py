"""Package closed runs and compute A-D counts from every attempted root."""
from collections import Counter
import gzip
import hashlib
import json
from math import log1p
from pathlib import Path
import os
import shutil
import statistics
import tempfile
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LOG=ROOT/"logs/hotsearch"
E=ROOT/"experiments/m1-infra1h3r/evidence"
STAGES={"natural":"natural.jsonl.gz","g2":"natural.jsonl.gz","strict":"natural.jsonl.gz","feedback":"natural.jsonl.gz","frozen":"replay.jsonl",
        "native":"results.jsonl","world-train":"worlds.jsonl.gz","world-dev":"worlds.jsonl.gz",
        "123":"worlds.jsonl.gz","pairs":"worlds.jsonl.gz"}
STRICT_WORLDS=("strict-train","strict-dev","strict123","strict-pairs")
STAGES.update(dict.fromkeys(STRICT_WORLDS,"worlds.jsonl.gz"))


def read(p):return json.loads(p.read_bytes())
def rows(path):return list(map(json.loads,gzip.open(path) if path.suffix==".gz" else path.open("rb")))
def pack(path,items):
    with path.open("wb") as stream,gzip.GzipFile(filename="",mode="wb",mtime=0,fileobj=stream) as gz:
        for row in items:gz.write(json.dumps(row,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()+b"\n")
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def count(values):return dict(Counter(values))
def score(r):
    if r["status"] in ("death","Defeat"):return -50.
    loss=r.get("opening_hp",r.get("hp"))-r["terminal"]["hp"]
    mx=r.get("opening_max_hp",r.get("max_hp"))
    mix=1. if mx>=500 else .5 if mx>100 else 0.
    value=(1-mix)*loss+mix*(10*log1p(max(loss,0)/10)+.05*max(loss,0)+min(loss,0))
    return 100-min(value,149)


def paired(left,right):
    ref={r["i"]:r for r in right}
    if {r["i"] for r in left}!=set(ref):raise ValueError("unmatched panel")
    pairs=[(r,ref[r["i"]]) for r in left if r.get("terminal") and ref[r["i"]].get("terminal")]
    if any(a["seed"]!=b["seed"] for a,b in pairs):raise ValueError("seed mismatch")
    diffs=[score(a)-score(b) for a,b in pairs]
    return dict(n=len(pairs),missing=len(left)-len(pairs),wins_gained=sum(a["status"]=="Victory" and b["status"] in ("death","Defeat") for a,b in pairs),
        wins_lost=sum(a["status"]=="Defeat" and b["status"] in ("predicted_win","Victory") for a,b in pairs),
        mean_delta=statistics.mean(diffs),median_delta=statistics.median(diffs))


def panel_stats(rs):
    qs=[q for r in rs for q in r["queries"]]
    options=[o for q in qs for o in [q["reference_law"],*q["options"]]]
    return dict(attempts=len(rs),status=count(r["status"] for r in rs),encounters=len({r["encounter"] for r in rs}),
        failures={r["i"]:r.get("reason") for r in rs if not r.get("terminal")},actual_steps=sum(r["actual_steps"] for r in rs),
        player_choices=sum(len(r["choices"]) for r in rs),C_completed=sum(len(r["states"]) for r in rs if r.get("terminal")),
        C_partial=sum(len(r["states"]) for r in rs if not r.get("terminal")),turn_queries=len(qs),candidate_and_reference=len(options),
        changed_turns=sum(q["committed"] for q in qs),changed_first=sum(q["reference"]!=q["selected"] for q in qs),
        full_laws=sum(o["value"] is not None for o in options),full_reference=sum(q["reference_law"]["value"] is not None for q in qs),
        mean_covered_mass=statistics.mean(o["coverage"] for o in options) if options else None,
        search_steps=sum(o["steps"] for o in options),chance_boundaries=sum(o["chances"] for o in options),
        pending_boundaries=sum(o["choices"] for o in options),realized_laws=count(str(q.get("matched")) for q in qs),
        gap_events=count(k for o in options for k in o["gaps"]))


def world_stats(rs):
    pairs=[w["outcomes"] for r in rs for w in r["worlds"]]
    natural=[r["natural_pair"] for r in rs if r["natural_pair"]]
    def matched(pair):return len(pair)==2 and all(a.get("public_matched") and a.get("matched") for a in pair)
    outcomes=[a for pair in pairs+natural for a in pair]
    accepted=[r for r in rs if r["status"]=="matched"]
    def delta(sides):
        return sides[0]["utility"]-sides[1]["utility"]
    natural_delta=[delta(r["natural_pair"]) for r in accepted]
    conditional_delta=[[delta(w["outcomes"]) for w in r["worlds"]] for r in accepted if r["worlds"]]
    means=[statistics.mean(d) for d in conditional_delta]
    contrasts=dict(accepted=len(accepted),
        natural_mean=statistics.mean(natural_delta) if natural_delta else None,
        conditional_root_mean=statistics.mean(means) if means else None,
        median_within_root_paired_mcse=statistics.median(statistics.stdev(d)/len(d)**.5 for d in conditional_delta)
            if conditional_delta and all(len(d)>1 for d in conditional_delta) else None)
    return dict(attempts=len(rs),paired_plan0_minus_plan1=contrasts,status=count(r["status"] for r in rs),terminal_sides=sum(a.get("status") in ("Victory","Defeat") for a in outcomes),
        paired_natural_matched=sum(map(matched,natural)),paired_natural_attempts=len(natural),
        world_pairs=len(pairs),matched_world_pairs=sum(map(matched,pairs)),admitted_world_pairs=sum(len(r["worlds"]) for r in rs if r["status"]=="matched"),
        invariant_roots=sum(r.get("invariant",False) for r in rs),search_steps_root=sum(r["work"] for r in rs),
        actual_steps_suffix=sum(a["actual_steps"] for a in outcomes),
        search_steps_completed_suffix=sum(a.get("search_steps",0) for a in outcomes),
        failures=count(r.get("reason","reached root") for r in rs if r["status"]=="failed"))


def transport_cost(folder):
    ops=Counter();physical=chance=choice=0;errors=Counter()
    for path in (folder/"transport").glob("*/commands.jsonl"):
        with path.open("rb") as f:
            for line in f:ops[json.loads(line).get("op","unknown")]+=1
    for path in (folder/"transport").glob("*/stdout.log"):
        with path.open("rb") as f:
            for line in f:
                if b'"type":"hot"' not in line[:60]:continue
                if b'"ok":false' in line[:60]:
                    errors[json.loads(line)["reason"]]+=1
                elif b'"result":[' in line[:80]:
                    for option in json.loads(line)["result"]:
                        physical+=option["steps"];chance+=option["chances"];choice+=option["choices"]
    return dict(commands=dict(ops),completed_search_rule_steps=physical,chance_stops=chance,
                choice_stops=choice,failed_requests=dict(errors))


def release(dest):
    if (dest/"sha256.json").exists():
        raise FileExistsError("sealed evidence already exists: "+str(dest))
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as work:
        stage=Path(work)
        assemble(stage)
        if dest.exists():
            for p in dest.iterdir():
                if not (stage/p.name).is_file() or sha(p)!=sha(stage/p.name):
                    raise ValueError("existing output differs: "+str(p))
        dest.mkdir(exist_ok=True)
        for p in sorted(stage.iterdir(),key=lambda p:p.name=="sha256.json"):
            if not (dest/p.name).exists():
                shutil.copyfile(p,dest/p.name)


def assemble(dest):
    data={};ledgers={}
    for name,filename in STAGES.items():
        folder=LOG/("formal-diagnostic" if name=="natural" else "formal-"+name)
        data[name]=rows(folder/filename)
        pack(dest/(name+".jsonl.gz"),data[name])
        ledgers[name]=read(folder/"ledger.json") if (folder/"ledger.json").exists() else {"wall":read(folder/"seconds.json")}
        if (folder/"transport").is_dir():ledgers[name]["physical"]=transport_cost(folder)
    old=ROOT/"logs/infra0-runs/infra1h-A-natural-h-batch"
    worker=read(old/"worker-0/worker.json")
    frozen=rows(old/"worker-0/evidence"/worker["closed"]["file"])
    reference=read(old/"result.json")
    native={r["i"]:r for r in data["native"]}
    prior={r["i"]:r for r in rows(LOG/"formal-natural/natural.jsonl.gz")}
    for r in data["natural"]+data["strict"]:
        if r["terminal"] and (r["trace"],r["choices"],r["terminal"])!=(prior[r["i"]]["trace"],prior[r["i"]]["choices"],prior[r["i"]]["terminal"]):
            raise ValueError("native evidence was produced on a different trajectory")
    admitted=[r for r in data["strict"] if r.get("terminal") and native[r["i"]]["status"]=="matched"]
    pack(dest/"natural-reviewed.jsonl.gz",admitted)
    c=[c for r in data["frozen"] for c in r["cuts"]]
    book=rows(LOG/"campaign/ledger.jsonl")
    book=[dict(label=a["label"],seconds=a["seconds"],exit=a["exit"],start_utc_unix=a["start_utc_unix"]) for a in book]
    ritsu=Path(os.environ.get("I1_RITSU",str(Path.home()/"Desktop/STEAM/steamapps/workshop/content/2868840/3747602295")))
    assets={str(p.relative_to(ROOT)).replace(chr(92),"/"):sha(p) for p in [
        ROOT/"logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt",ROOT/"experiments/m1-core5a/evidence/v2.pt",
        ROOT/"experiments/m1-core5d/evidence/panel.gz",ROOT/"logs/infra0-world-inputs/panel.gz",
        ROOT/"experiments/m1-infra0/panel.json",LOG/"oracle/bin/Release/net9.0/OfflineSearchHarness.dll"]}
    assets.update({"RitsuLib/"+p.relative_to(ritsu).as_posix():sha(p) for p in ritsu.rglob("*.dll")})
    rebuilt=rows(LOG/"formal-final/natural.jsonl.gz")
    def stable(r):
        return {k:v for k,v in r.items() if k!="seconds"}
    if list(map(stable,rebuilt))!=list(map(stable,data["strict"])):
        raise ValueError("rebuilt release did not reproduce the strict panel")
    repeat=dict(identical=len(rebuilt),ledger=read(LOG/"formal-final/ledger.json"))
    initial=rows(LOG/"formal-custom/natural.jsonl.gz")
    repeat["initial_recovery_failure"]=[dict(status=r["status"],reason=r.get("reason")) for r in initial]
    custom=rows(LOG/"formal-recovery/natural.jsonl.gz")
    if [r["status"] for r in custom]!=["Victory","failed","Victory"] or any(r["split"]!="custom" for r in custom):
        raise ValueError("custom complete / rejected / reopened sequence")
    if custom[0]["trace"]!=custom[2]["trace"] or custom[0]["terminal"]!=custom[2]["terminal"]:
        raise ValueError("failed open affected the next battle")
    native_launch,=rows(LOG/"formal-native-launch/results.jsonl")
    if native_launch["status"]!="matched":raise ValueError("native launch")
    repeat.update(custom=[dict(status=r["status"],reason=r.get("reason"),steps=r["actual_steps"]) for r in custom],
                  native_launch=native_launch,recovery_host=read(LOG/"formal-recovery/ledger.json")["host"])
    report=dict(inputs=assets,rebuilt=repeat,measured_build=read(LOG/"formal-strict/identity.json"),start="699f8988f88ab8ba0c2148f8284b108f3dd4f6dd",build=read(LOG/"identity.json"),
        native=count(r["status"] for r in data["native"]),native_stops=[r for r in data["native"] if r["status"]!="matched"],
        frozen=dict(roots=len(data["frozen"]),replay=count(r["status"] for r in data["frozen"]),cuts=len(c),
            equal_tensors=sum(x["tensor_equal"] for x in c),equal_C=sum(not x["different"] for x in c),
            different_fields=count(k for x in c for k in x["different"])),
        natural=panel_stats(data["natural"]),g2=panel_stats(data["g2"]),strict=panel_stats(data["strict"]),feedback=panel_stats(data["feedback"]),reviewed=dict(battles=len(admitted),cuts=sum(len(r["states"]) for r in admitted)),
        worlds={k:world_stats(data[k]) for k in ("world-train","world-dev","123","pairs",*STRICT_WORLDS)},ledgers=ledgers,campaign=book,
        historical=dict(status=count(r["status"] for r in frozen),production_seconds=reference["production_wall_s"],totals=reference["totals"],
            python_cpu=worker["python_cpu_ns"]/1e9,host=worker["host_resources"],python=worker["python_resources"]),
        paired_feedback=paired(data["feedback"],data["g2"]),paired_g2=paired(data["natural"],data["g2"]),paired_frozen=paired(data["natural"],frozen))
    (dest/"summary.json").write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode("utf8"))
    manifest={p.name:sha(p) for p in sorted(dest.iterdir())}
    (dest/"sha256.json").write_bytes((json.dumps(manifest,indent=2)+"\n").encode("utf8"))


if __name__=="__main__":release(Path(sys.argv[1]) if len(sys.argv)>1 else E)
