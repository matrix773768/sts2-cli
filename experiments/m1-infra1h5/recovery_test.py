"""One real strict battle, fault immediately before publication, reopen and retry exactly once."""
from pathlib import Path
import gzip,json,os,subprocess,sys,time
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"engine/HotSearch"))
from produce_batch import execute,exclusive,tasks
from experience import read_rows,sha

def experiment(folder,crash=False):
    plan=json.loads((HERE/"data/plan.json").read_bytes())
    job=tasks(json.load(gzip.open(HERE/"cohort.json.gz")),plan["id"])[0]
    args=SimpleNamespace(data=folder/"data",work=folder/"work",build=ROOT/"logs/hotsearch-h5")
    for path in (args.data/"shards",args.data/".pending",args.work):path.mkdir(parents=True,exist_ok=True)
    group=("fixture",[job]);dest=args.data/"shards/fixture"
    if crash:
        original=Path.rename
        def fail_before_publish(src,target):
            if target==dest and (src/"receipt.json").is_file():os._exit(73)
            return original(src,target)
        Path.rename=fail_before_publish
        execute(group,args,plan)
        raise ValueError("did not reach fault")
    start=time.perf_counter()
    proc=subprocess.run([sys.executable,"-B",__file__,str(folder),"crash"])
    assert proc.returncode==73 and not dest.exists()
    incomplete,=(args.data/".pending").iterdir()
    restarted,reuse=execute(group,args,plan);assert not reuse
    first,=read_rows(incomplete/"rows.gz");second,=read_rows(dest/"rows.gz")
    for row in (first,second):row["trajectory"].pop("seconds")
    assert first==second
    repeated,skip=execute(group,args,plan)
    assert skip and restarted==repeated and len(list((args.data/"shards").iterdir()))==1
    with exclusive(folder/"lock"):
        child=subprocess.run([sys.executable,"-B",__file__,str(folder),"lock"],capture_output=True)
        assert child.returncode==74
    (folder/"result.json").write_text(json.dumps(dict(crash_exit=73,visible_before_retry=0,attempts=2,visible_after_retry=1,
        replayed_semantics_identical=True,duplicate_skipped=skip,writer_exclusion=True,wall=time.perf_counter()-start,
        task=job["id"],shard_sha256=sha(dest/"rows.gz"))))
if __name__=="__main__":
    path=Path(sys.argv[1]).resolve()
    if sys.argv[2:]==["lock"]:
        try:
            with exclusive(path/"lock"):sys.exit(0)
        except OSError:sys.exit(74)
    experiment(path,sys.argv[2:]==["crash"])
