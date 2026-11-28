"""Run the frozen external high-budget 1A worker on the preregistered open inputs."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def run():
    out=ROOT/"logs/hotsearch-h4/open-reference"
    (out/"evidence").mkdir(parents=True,exist_ok=False)
    (out/"tmp").mkdir()
    panel=json.loads((HERE/"evidence/open-specs.json").read_bytes())
    with gzip.open(out/"evidence/panel.gz","wt") as f:json.dump({"train":panel},f)
    task=dict(smoke=False,kind="natural",arm="V2",mode="baseline",ids=list(range(len(panel))),folder=str(out),variant="h-batch")
    path=out/"task.json";path.write_text(json.dumps(task))
    env={k:v for k,v in os.environ.items() if not k.startswith(("STS2_CORE","CORE5","I1_"))}
    env.update(PYTHONDONTWRITEBYTECODE="1",PYTHONHASHSEED="0",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    subprocess.run([sys.executable,"-B",ROOT/"experiments/m1-infra0/worker.py",path],cwd=ROOT,env=env,check=True)

if __name__=="__main__":run()
