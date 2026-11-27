"""Record phase timers, exact deployed assets and digests of the archived decisions."""
import gzip,json,hashlib
from panel5c import E,HERE,OUT,HOST,ROOT,FIVE
from cohort import PARENT
def sha(path):
    blob=path.read_bytes()
    if path.suffix in (".py",".json"):
        blob=blob.replace(b"\r\n",b"\n")
    return hashlib.sha256(blob).hexdigest()
def load(p):
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix==".gz" else p.read_bytes())
def main():
    build=load(HOST/"build.json")
    phases={"build":build["build_seconds"]}
    for p in sorted(OUT.glob("*/seconds.json")):
        phases[p.parent.name]=load(p)
    for name in ("placement","verification","mechanisms","native-loss","native-rescue","stress-multiset-4096","stress-ordered-4096","stress-ordered-32"):
        data=load(E/(name+".json"))
        phases[name]=data.get("wall",data["seconds"])
    for tag in ("loss","rescue"):
        phases["witness-"+tag]=load(E/f"witness-{tag}.gz")["seconds"]
    tests=load(E/"regression.json")
    assert all(x["status"]==0 for x in tests.values())
    phases["regression_suites"]=sum(r["seconds"] for r in tests.values())
    old=load(HERE.parent/"m1-core5b/evidence/ledger.json")
    weights={k:sha((FIVE if k=="v2" else HERE.parent/"m1-core4")/"evidence"/(k+".pt")) for k in ("v0","v1","v2")}
    assert weights==old["weights"] and sha(PARENT)==old["g2_pinned_sha256"]
    rules=load(FIVE/"evidence/manifest.json")["static_rules_sha256"]
    assert all(sha(HERE.parent/name)==value for name,value in rules.items())
    data=dict(start="b7e94855c108ec761dfa9532a4f16950434bb536",measured_worker_seconds=sum(phases.values()),
       scope="Sum of measured worker wall intervals. Concurrent workers count separately. Timed battles include native lane startup, planning, model scoring, execution, reset and I/O. Module import before phase entry is excluded.",
       unmetered="Early setup/import failures, intermediate directed witnesses, first regression invocation, panel generation, printing and inspection were not all individually metered. Allow roughly another 7 worker minutes for trial runs, an estimate.",
       phases=phases,weights=weights,g2=sha(PARENT),host=build["artifacts"],game=build["game"],
       panel_sha256=sha(E/"protocol.gz"),static_rules=rules,
       files={p.name:sha(p) for p in sorted(E.iterdir()) if p.is_file() and p.name!="ledger.json"},
       source_hashes={p.name:sha(p) for p in sorted(HERE.glob("*.py"))},text_hash="LF-normalized for JSON and Python; compressed files hashed as stored.")
    (E/"ledger.json").write_text(json.dumps(data,indent=2))
if __name__=="__main__":
    main()
