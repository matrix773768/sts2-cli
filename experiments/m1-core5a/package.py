"""Package measured study jobs, serialized diagnostics and file identities."""
from pathlib import Path
import hashlib,json,shutil,sys,platform
from metrics import E,FIVE,report
from core4_roots import ROOT
from semantic import torch,np

def read(path):return json.loads(path.read_bytes())
def sha(path):
    data=path.read_bytes()
    if path.suffix in (".json",".cs",".py",".md"):data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()
def span(path):
    files=[p.stat() for p in path.rglob("*") if p.is_file()]
    return max([path.stat().st_ctime]+[f.st_mtime for f in files])-path.stat().st_ctime

def package(formal,bench,teacher,audit):
    for path in (bench/"benchmark.json",teacher/"teacher.json",teacher/"worlds.gz",audit/"audit.json"):
        shutil.copyfile(path,E/path.name)
    identity=read(ROOT/"logs/core5a-host3/build.json")
    identity.pop("build_seconds",None)
    identity["timing_source"]="See ledger for incremental build and clean reproduction."
    (E/"host.json").write_text(json.dumps(identity,indent=2))
    shutil.copyfile(formal/"regression.json",E/"regression.json")
    report()
    jobs={p.parent.name:read(p) for p in sorted(formal.glob("*/cost.json"))}
    benchmark=read(E/"benchmark.json")
    phases=dict(final_regression=sum(r["seconds"] for r in read(formal/"regression.json")),production_development_and_confirmation=sum(x["seconds"] for x in jobs.values()),
        training=read(E/"fit.json")["seconds"],
        reproduced_training=read(ROOT/"logs/5a-fit-check/fit.json")["seconds"],
        reproduced_build=read(ROOT/"logs/core5a-build-recheck/build.json")["build_seconds"],independent_teacher=read(E/"teacher.json")["seconds"],
        reference_audit=read(E/"audit.json")["seconds"],controlled_timing=sum(r["wall"] for r in benchmark["runs"]))
    # File timestamps bound uninstrumented build/debug processes, including idle repair gaps.
    prep={p.name:span(p) for pattern in ("core5a-host","core5a-host2","core5a-host3","5a-check","5a-check2","5a-check3","5a-check4")
          for p in (ROOT/"logs").glob(pattern)}
    # Copies may retain old source timestamps; restrict to artifacts produced in this run.
    replica=ROOT/"logs/core5a-build-recheck"
    deployed=ROOT/"logs/core5a-host3"
    verification=dict(checkpoint_sha256=sha(E/"v2.pt"),retrained_sha256=sha(ROOT/"logs/5a-fit-check/model.pt"),
        generated_source_match={name:sha(replica/"host/Headless"/name)==sha(deployed/"host/Headless"/name)
        for name in ("Tactical.cs","Reference.cs","Strategic.cs","IntegrationProbe.cs")})
    ledger=dict(verification=verification,worker_jobs=jobs,phase_seconds=phases,measured_seconds=sum(phases.values()),
                build_and_debug_file_span_estimates=prep,
                formal_batch_elapsed_seconds=max(p.stat().st_mtime for p in formal.glob("*/cost.json"))-formal.stat().st_ctime,
                excludes="Human implementation time and uninstrumented per-process Python import/exit except controlled timing; batch elapsed overlaps workers.")
    (E/"ledger.json").write_text(json.dumps(ledger,indent=2))
    manifest=dict(text_hash="LF-normalized UTF-8",start="4cc5b0009750c2b0b4d4cf02dfe791dc67865a9e",
        g2=read(FIVE.parent/"m1-core4/evidence/manifest.json")["G2_sha256"],
        v1=sha(FIVE.parent/"m1-core4/evidence/v1.pt"),continuation="repaired frozen CORE-4 V1",
        value_class="experiments/m1-core4/semantic.py Value",parameters=31596,
        static_rules_sha256={str(p.relative_to(FIVE.parent).as_posix()):sha(p) for p in (
            FIVE.parent/"m1-core2/catalog.json.gz",FIVE.parent/"m1-core4/cards.json.gz")},
        python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,
        evidence={p.name:sha(p) for p in sorted(E.iterdir()) if p.name!="manifest.json"})
    (E/"manifest.json").write_text(json.dumps(manifest,indent=2))
if __name__=="__main__":package(*map(Path,sys.argv[1:]))
