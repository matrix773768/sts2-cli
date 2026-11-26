"""Run bounded parallel shards, keeping previously completed evidence immutable."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,sys,subprocess,shutil,time,os
HERE=Path(__file__).resolve().parent


def study(out):
    out.mkdir(parents=True,exist_ok=True)
    evidence=out/"evidence"
    evidence.mkdir(exist_ok=True)
    def work(job):
        group,arm,rep,shard,n=job
        path=out/f"{group}-{arm}-{rep}-{shard}"
        if not (path/"cost.json").exists():
            subprocess.run([sys.executable,str(HERE/"produce.py"),str(path),group,arm,
                            str(rep),str(shard),str(n)],check=True,env=os.environ|dict(CORE5A_V2=str(evidence/"v2.pt")))
        cost=json.loads((path/"cost.json").read_bytes())
        if cost["errors"]>4:raise RuntimeError(f"Check errors in {path}")
        shutil.copyfile(path/"rows.gz",evidence/(path.name+".gz"))
    def batch(jobs,workers):
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(work,jobs))
    def jobs(group,arm,repeats,shards):
        return [(group,arm,r,s,shards) for r in range(repeats) for s in range(shards)]
    # Run matched timing arms serially in identical conditions.
    batch(jobs("dev","slow",1,1)+jobs("dev","fast",1,1),1)
    batch(jobs("dev","v1",1,1)+jobs("train","v1",2,3),3)
    if not (out/"fit/fit.json").exists():
        from search5 import FIVE
        from train_value4 import run
        run(out/"fit",str(HERE.parent/"m1-core4/evidence/v1.pt"),
            [*sorted(evidence.glob("train-v1-*.gz")),*evidence.glob("dev-v1-*.gz")],continuation="v1")
    shutil.copyfile(out/"fit/model.pt",evidence/"v2.pt")
    shutil.copyfile(out/"fit/fit.json",evidence/"fit.json")
    batch([j for arm in ("G2","G2search","original","v1","v2") for j in jobs("confirm",arm,3,1)],3)
if __name__=="__main__":study(Path(sys.argv[1]))
