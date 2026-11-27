"""Measured worker wall times, frozen identities, artifact and implementation digests."""
import json,hashlib
from collections import defaultdict
from panel5d import E,HERE,FIVE,ROOT,load
from cohort import PARENT

def sha(path):
    data=path.read_bytes()
    if path.suffix in (".md",".json",".py"):data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()

def main():
    phases={};category=defaultdict(float)
    def add(group,name,seconds):
        phases[name]=seconds;category[group]+=seconds
    def read(name):return json.loads((E/name).read_bytes())
    for f in sorted(E.glob("*.time.json")):
        name=f.name.split(".")[0];group=name.split("-")[0].rstrip("2")
        add(group,name,json.loads(f.read_bytes()))
    for name in ("fit","pilot-fit","verification","audit","flips","replay-check","relic-panel"):
        add("fit" if name in ("fit","pilot-fit","verification") else "audit",name,read(name+".json")["seconds"])
    add("build","replay-host",read("replay-check.json")["build"]["build_seconds"])
    for name in ("tests","tests-initial"):
        for suite,row in read(name+".json").items():add("tests",name+"-"+suite,row["seconds"])
    for stem in ("run-*","recovered-*","progression-*","late-roots"):
        for f in E.glob(stem+".gz"):add("native",f.stem,load(f)["seconds"])
    add("analysis","shared",read("results.json")["shared"]["seconds"])
    old=json.loads((HERE.parent/"m1-core5c/evidence/ledger.json").read_bytes())
    weights={k:sha((FIVE if k=="v2" else HERE.parent/"m1-core4")/"evidence"/(k+".pt")) for k in ("v0","v1","v2")}
    assert weights==old["weights"] and sha(PARENT)==old["g2"]
    assert all(sha(HERE.parent/name)==value for name,value in old["static_rules"].items())
    weights["v3"]=sha(E/"v3.pt")
    host=json.loads((ROOT/"logs/core5c-host/build.json").read_bytes())
    assert host["artifacts"]==old["host"]
    inputs={str(p.relative_to(ROOT)):sha(p) for p in [*HERE.glob("*.py"),HERE/"protocol.md",
        HERE.parent/"m1-core4/play_loop.py",HERE.parent/"m1-core5c/complete.py",HERE.parent/"m1-core5c/policy5c.py"]}
    data=dict(start="5b8f52497ff5c2f9c0344fef09a9e5829f2b51bf",worker_seconds=sum(phases.values()),categories=category,
        phases=phases,g2=sha(PARENT),weights=weights,game=host["game"],host=host["artifacts"],static=old["static_rules"],sources=inputs,
        scope="Worker wall time summed across parallel processes. Battles include setup after module import, simulation, inference, execution, lane reset and output. Controlled cost trials use identical 16 roots.",
        unmetered="Module import/startup before timers, early diagnostic failures, aggregation and authoring are outside measured intervals. Timing is not CPU time; concurrent work can affect elapsed latency.",
        evidence={p.name:sha(p) for p in sorted(E.iterdir()) if p.is_file() and p.name!="ledger.json"},
        text_hash="LF-normalized for text sources and JSON. Binary and gzip hashed as stored.")
    (E/"ledger.json").write_text(json.dumps(data,indent=2))
if __name__=="__main__":main()
