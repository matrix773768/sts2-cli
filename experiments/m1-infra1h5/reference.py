"""Run the external corrected 1A reference once on the preregistered open cohort."""
import gzip,json,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def run(out):
    start=time.perf_counter()
    (out/"evidence").mkdir(parents=True,exist_ok=False)
    (out/"tmp").mkdir()
    with gzip.open(out/"evidence/panel.gz","wt") as z:
        json.dump({"train":json.load(gzip.open(HERE/"cohort.json.gz"))["open"]},z)
    task=dict(smoke=False,kind="natural",arm="V2",mode="baseline",ids=list(range(64)),folder=str(out.resolve()),variant="h-batch")
    path=out/"task.json";path.write_text(json.dumps(task))
    env={k:v for k,v in os.environ.items() if not k.startswith(("STS2_CORE","CORE5","I1_"))}
    env.update(PYTHONDONTWRITEBYTECODE="1",PYTHONHASHSEED="0",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    subprocess.run([sys.executable,"-B",ROOT/"experiments/m1-infra0/worker.py",path],cwd=ROOT,env=env,check=True)
    (out/"wall.json").write_text(json.dumps(time.perf_counter()-start))
if __name__=="__main__":run(Path(sys.argv[1]))
