"""Seal the H4 campaign. Keep population-level and independently admitted samples separate."""
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import shutil
import statistics
import tempfile
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LOG=ROOT/"logs/hotsearch-h4"
DEST=HERE/"evidence"
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from release import pack,paired,panel_stats,read,rows,score,sha,world_stats

ARMS=("g2","light","quality32","quality128","quality512","candidate32","composed32","composed128","composed512","open-hot","open-g2","post-open-fixed","post-fix96","final-g2","final-light")
WORLDS=("worlds123","pairs","candidate123","candidate-pairs","release123")
STEP=re.compile(rb'\{"index":\d+,"steps":(\d+),"chances":(\d+),"choices":(\d+)')

def dump(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode())

def meter(folder):
    commands=Counter();steps=chance=choices=0
    for path in (folder/"transport").glob("*/commands.jsonl"):
        commands.update(json.loads(s)["op"] for s in path.open("rb"))
    for path in (folder/"transport").glob("*/stdout.log"):
        with path.open("rb") as stream:
            for line in stream:
                if line.startswith(b'{"type":"hot","ok":true,"result":['):
                    for a,b,c in STEP.findall(line):
                        steps+=int(a);chance+=int(b);choices+=int(c)
    return dict(commands=dict(commands),searched_rule_steps=steps,chance=chance,choices=choices,
                requested_real_steps=commands["step"])

def oldrun(folder,open_panel):
    worker=folder if open_panel else folder/"worker-0"
    w=read(worker/"worker.json")
    data=rows(worker/"evidence"/w["closed"]["file"])
    cost={k:w[k] for k in ("python_cpu_ns","host_resources","python_resources")}
    if not open_panel:cost["telemetry"]=read(folder/"result.json")["totals"]
    cost["wall"]=(w["done_ns"]-w["entry_ns"])/1e9 if open_panel else read(folder/"result.json")["production_wall_s"]
    return data,cost

def utility(data):
    done=[r for r in data if r.get("terminal")]
    return dict(completed=len(done),wins=sum(r["status"] in ("Victory","predicted_win") for r in done),
        mean_utility=statistics.mean(map(score,done)),mean_hp_loss=statistics.mean(r.get("opening_hp",r.get("hp"))-r["terminal"]["hp"] for r in done),
        C=sum(len(r["states"]) for r in done))

def assemble(dest):
    datasets={}
    book={"arms":{},"worlds":{},"controls":{}}
    for name in ARMS:
        folder=LOG/name
        rs=rows(folder/"natural.jsonl.gz");datasets[name]=rs
        pack(dest/(name+".jsonl.gz"),rs)
        result=book["arms"][name]=panel_stats(rs)|utility(rs)
        result["cost"]=read(folder/"ledger.json")
        result["physical"]=meter(folder)
        result["selected_styles"]=dict(Counter(q.get("winner_style","reference") for r in rs for q in r["queries"]))
        review=LOG/("review-"+name)
        if review.is_dir() and (review/"ledger.json").exists():
            result["review"]=read(review/"ledger.json")
            shutil.copyfile(review/"review.jsonl.gz",dest/(name+"-native.jsonl.gz"))
            if name in ("candidate32","open-hot"):
                shutil.copyfile(review/"reviewed.jsonl.gz",dest/(name+"-reviewed.jsonl.gz"))
        if name in ("candidate32","quality32"):
            native=LOG/("full-native-candidate32" if name=="candidate32" else "reviewed32")
            verdict=rows(native/"results.jsonl");pack(dest/(name+"-full-native.jsonl.gz"),verdict)
            accepted={r["i"] for r in verdict if r["status"]=="matched"}
            result["full_review"]=read(native/"ledger.json")|dict(reviewed=len(accepted),C=sum(len(r["states"]) for r in rs if r["i"] in accepted))
    for name,source in [("1A",ROOT/"logs/infra0-runs/infra1h-A-natural-h-batch"),("open-1A",LOG/"open-reference")]:
        rs,cost=oldrun(source,name.startswith("open"));datasets[name]=rs
        pack(dest/(name+".jsonl.gz"),rs)
        book["controls"][name]=utility(rs)|dict(cost=cost)
    h3=rows(ROOT/"experiments/m1-infra1h3r/evidence/strict.jsonl.gz")
    for name,c in book["arms"].items():
        refs=["open-g2","open-1A"] if name.startswith("open") or name=="post-open-fixed" else ["g2","light","1A"]
        if name in ("post-fix96","final-g2","final-light"):
            refs=["final-g2","final-light","1A","candidate32"]
        c["paired"]={ref:paired(datasets[name],datasets[ref]) for ref in refs if ref!=name}
        if name!="post-open-fixed" and not name.startswith("open"):c["paired"]["h3-strict"]=paired(datasets[name],h3)
    for name in WORLDS:
        folder=LOG/name
        rs=rows(folder/"worlds.jsonl.gz")
        pack(dest/(name+".jsonl.gz"),rs)
        native=[side["native"] for r in rs for pair in [r["natural_pair"],*[w["outcomes"] for w in r["worlds"]]] for side in pair if "native" in side]
        book["worlds"][name]=world_stats(rs)|dict(cost=read(folder/"ledger.json"),native=dict(Counter(v["status"] for v in native)),physical=meter(folder))
    for name,source in [("selected-laws","closed-laws-batches/laws.jsonl.gz"),("selected-states","closed-laws-batches/states.jsonl.gz"),("budget512-differences","composed512-differences/findings.jsonl.gz"),("open-differences","open-differences/findings.jsonl.gz"),("historical-failure-replay","replay-failures/replay.jsonl.gz"),("native-draw-cuts","ordered-cuts/cuts.jsonl.gz"),("frozen-replay","frozen/replay.jsonl")]:
        pack(dest/(name+".jsonl.gz"),rows(LOG/source))
    book["builds"]={name:read(ROOT/"logs"/name/"identity.json") for name in ("hotsearch-h4","hotsearch-h4-candidate","hotsearch-h4-public-fix")}
    book["native_followups"]={}
    for name,source,description in [("gardens-native","candidate32","原园丁三根使用补全数学函数的审核宿主"),
                                    ("post96-native","post-fix96","当前源码的战术 32 全面板逐条原生重放"),
                                    ("post-open-native","post-open-fixed","后验开放回测全体根逐条原生重放"),
                                    ("release96-native","post-fix96","补齐场景树接口后，当前战术 32 全面板原生重放"),
                                    ("release-open-native","post-open-fixed","补齐场景树接口后，后验开放面板原生重放")]:
        folder=LOG/name;verdict=rows(folder/"results.jsonl")
        pack(dest/(name+".jsonl.gz"),verdict)
        ids={r["i"] for r in verdict if r["status"]=="matched"}
        admitted=[r for r in datasets[source] if r["i"] in ids]
        if name.startswith("release"):pack(dest/(source+"-reviewed.jsonl.gz"),admitted)
        book["native_followups"][name]=dict(description=description,status=dict(Counter(r["status"] for r in verdict)),
            reviewed=len(ids),C=sum(len(r["states"]) for r in admitted),cost=read(folder/"ledger.json"))
    incidents=[]
    by_seed={r["seed"]:r["i"] for r in datasets["candidate32"]}
    for path in sorted((LOG/"full-native-candidate32/native").glob("*/stderr.log")):
        lines=path.read_text(encoding="utf8",errors="replace").splitlines()
        missing=next((line for line in lines if "MissingMethodException" in line and "Mathf.Log" in line),None)
        if missing:
            command=json.loads(next((path.parent/"commands.jsonl").open("rb")))
            incidents.append(dict(i=by_seed[command["spec"]["seed"]],error=missing,sha256=sha(path),
                native_frame=next(line.strip() for line in lines if "PhantasmalGardener.EnlargeMove" in line)))
    if {r["i"] for r in incidents}!={23,86,89}:raise ValueError("native incident provenance")
    dump(dest/"oracle-host-gap.json",incidents)
    worker=read(LOG/"open-reference/worker.json")
    book["runtime"]=dict(python=worker["python"],torch=worker["torch"],threads=worker["threads"],
                         interop=worker["interop"],dotnet="9.0.7",hotkernel="1.0.2")
    book["inputs"]={path.relative_to(ROOT).as_posix():sha(path) for path in [
        ROOT/"experiments/m1-infra0/panel.json",ROOT/"experiments/m1-core5d/evidence/panel.gz",
        ROOT/"logs/infra0-world-inputs/panel.gz",ROOT/"logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt",
        ROOT/"experiments/m1-core5a/evidence/v2.pt"]}
    book["native_binaries"]={oracle:{name:sha(LOG/oracle/"bin/Release/net9.0"/name) for name in ("OfflineSearchHarness.dll","GodotSharp.dll")} for oracle in ("math-oracle","scene-oracle")}
    book["campaign"]=[dict(label=r["label"],seconds=r["seconds"],exit=r["exit"],start=r["start_utc_unix"],args=[str(a).replace(str(ROOT),"REPO") for a in r["args"][3:]]) for r in rows(LOG/"campaign/ledger.jsonl")]
    book["worker_seconds"]=sum(w["seconds"] for w in book["campaign"])
    dump(dest/"ledger.json",book)
    dump(dest/"sha256.json",{p.name:sha(p) for p in sorted(dest.iterdir()) if p.is_file() and p.name!="sha256.json"})

def run():
    seeds=("open-specs.json","public-counters.json","h3-first-difference.json.gz","h3-tensors.json.gz",
           "h4-tensors.json.gz","quality32-first-difference.json.gz","post-open-first-difference.json.gz")
    with tempfile.TemporaryDirectory(dir=LOG) as tmp:
        stage=Path(tmp)
        for name in seeds:shutil.copyfile(DEST/name,stage/name)
        assemble(stage)
        for path in DEST.iterdir():
            other=stage/path.name
            if not other.is_file() or sha(path)!=sha(other):
                raise ValueError("existing evidence differs: "+path.name)
        for path in sorted(stage.iterdir(),key=lambda p:p.name=="sha256.json"):
            if not (DEST/path.name).exists():shutil.copyfile(path,DEST/path.name)

if __name__=="__main__":run()
