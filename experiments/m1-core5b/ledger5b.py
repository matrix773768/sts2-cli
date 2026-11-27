"""Account summed worker elapsed seconds separately from aggregate run wall-clock."""
import json,gzip,hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
from paths5b import E
def read(path):return json.loads(path.read_bytes())
def sha(path):
    data=path.read_bytes()
    if path.suffix==".json":data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()

def main():
    phases={}
    for pattern in ("historical-base-*.json","historical-ref768-*.json","fresh-*.json","high-*.json","beam-*.json"):
        phases[pattern]=sum(read(f) for f in E.glob(pattern))
    for f in E.glob("*-cost.json"):phases[f.stem]=read(f)
    for name in ("audit","hp-native","hp-replay","long-turns","candidate-audit","cost-breakdown","pending-review"):
        phases[name]=read(E/(name+".json"))["seconds"]
    tests=read(E/"regression.json")
    phases["six_regression_suites"]=sum(s["seconds"] for s in tests.values())
    build=read(ROOT/"logs/core5b-host/build.json")
    phases["build"]=build["build_seconds"]
    old=read(HERE.parent/"m1-core5a/evidence/manifest.json")
    weights={name:sha(HERE.parent/folder/"evidence"/(name+".pt")) for name,folder in (
        ("v0","m1-core4"),("v1","m1-core4"),("v2","m1-core5a"))}
    assert weights["v1"]==old["v1"]
    assert weights["v2"]==read(HERE.parent/"m1-core5a/evidence/ledger.json")["verification"]["checkpoint_sha256"]
    data=dict(start="32fe39e69e740fc4f20781663ad42512d8a43a34",measured_worker_seconds=sum(phases.values()),
        phases=phases,scope="Worker phase timers, including cold battle setup where timed. Concurrent jobs charged by sum. Not CPU time or the elapsed span of the chat.",
        excluded="Exploratory failed diagnostic commands, first HP terminal-reader attempt, first test invocation, reporting and file inspection not individually metered. Conservatively allow another 180 worker seconds for these short starts and repeated tests; this allowance is not a measurement.",
        estimated_allowance_seconds=180,
        observations=dict(fresh_battles=480,historical_new_battles=576,high_hp_battles=240,oracle_f3b_searches=120,oracle_beam_searches=40),
        weights=weights,g2_pinned_sha256=old["g2"],host=build["artifacts"],solver_base=build["base_solver"],game=build["game"],
        python=old["python"],torch=old["torch"],panel_sha256=sha(E/"panel.gz"),
        artifact_hash_format="JSON uses LF line endings. Binary files are hashed verbatim.",
        artifact_sha256={f.name:sha(f) for f in sorted(E.iterdir()) if f.is_file() and f.name!="ledger.json"})
    (E/"ledger.json").write_text(json.dumps(data,indent=2))
if __name__=="__main__":main()
