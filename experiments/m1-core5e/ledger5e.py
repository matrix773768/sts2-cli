"""Sum worker-wall intervals and pin all evidence, models, rules and source inputs."""
import hashlib,json
from collections import defaultdict
from panel5e import E,D,ROOT,HERE,WORLD,FIVE
from cohort import PARENT

def sha(path):
    data=path.read_bytes()
    if path.suffix in (".json",".md",".py"):data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()
def run():
    read=lambda path:json.loads(path.read_bytes())
    phases={};categories=defaultdict(float)
    def add(name,group,seconds):
        phases[name]=seconds;categories[group]+=seconds
    for f in E.glob("*.time.json"):
        name=f.name.split(".")[0];add(name,name.split("-")[0],read(f))
    for name in ("fit","transitions","known","verification","results"):
        add(name,name,read(E/(name+".json"))["seconds"])
    for k,v in read(E/"tests.json").items():add(k,"tests",v["seconds"])
    build=read(WORLD/"build.json");add("build","build",build["build_seconds"])
    original=read(D/"ledger.json")
    weights={k:sha((HERE.parent/"m1-core4" if k in ("v0","v1") else FIVE if k=="v2" else D.parent)/"evidence"/(k+".pt"))
             for k in ("v0","v1","v2","v3")}
    assert weights==original["weights"] and sha(PARENT)==original["g2"]
    for k,v in original["static"].items():assert sha(HERE.parent/k)==v
    frozen=read(ROOT/"logs/core5c-host/build.json")
    assert frozen["artifacts"]==original["host"]
    reference=(WORLD/"host/Headless/Reference.cs").read_text(encoding="utf-8-sig")
    before,marker,after=reference.partition('if(request.TryGetProperty("diagnostic_world"')
    base_reference=(ROOT/"logs/core5c-host/host/Headless/Reference.cs").read_text(encoding="utf-8-sig")
    assert marker and before+after[after.index('if(request.TryGetProperty("clear",out _))'):]==base_reference
    consumed=[D/"panel.gz",D/"augmentation.gz",D/"flips.json"]
    for split in ("train","train2","dev","dev2"):
        consumed.extend(D.glob(split+"-V2-*.gz"));consumed.extend(D.glob("pairs-"+split+"-*.gz"))
    sources=[*HERE.glob("*.py"),HERE/"protocol.md",HERE.parent/"m1-core5b/build_turn_review.py",D.parent/"battle5d.py"]
    res=dict(start="5bb7c68bbb66e25b419460743d09f74568ca3372",worker_seconds=sum(phases.values()),phases=phases,categories=categories,
        weights=weights|{k:sha(E/(k+".pt")) for k in ("mc","td")},G2=sha(PARENT),static=original["static"],
        host=frozen["artifacts"],world_host=build,reference_source_equal_after_removing_sampler=True,
        game=frozen["game"],recovery_host=read(ROOT/"logs/core5d/replay-host/build.json")["artifacts"],
        scope="Sum of worker wall intervals including model inference, native episodes, suffixes, administration after module import and in-worker writes. Parallel workers count separately. Imports, panel setup, exploratory inspection, reliability summary and authoring outside timed phases are unmetered.",
        frozen_inputs={p.name:sha(p) for p in sorted(consumed)},
        sources={p.relative_to(ROOT).as_posix():sha(p) for p in sources},
        evidence={p.name:sha(p) for p in sorted(E.iterdir()) if p.is_file() and p.name!="ledger.json"},
        hash_convention="LF-normalized JSON, Markdown and Python; gzip and models hashed as stored.")
    (E/"ledger.json").write_text(json.dumps(res,indent=2))
if __name__=="__main__":run()
