"""Recreate the learning and confirmation pipeline in a new directory using frozen 5A–C hosts."""
import json,os,subprocess,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

def run(destination):
    here=Path(__file__).resolve().parent
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=False)
    env=os.environ|{"STS2_CORE5D_RUN":str(dest)}
    def call(job):
        script,*args=job
        subprocess.run([sys.executable,str(here/(script+".py")),*map(str,args)],env=env,cwd=here.parents[1],check=True)
    def batch(jobs):
        with ThreadPoolExecutor(max_workers=4) as workers:list(workers.map(call,jobs))
    call(("panel5d",));call(("augment5d",))
    batch([("battle5d",split,"V2",i,n) for split,n in (("train",4),("dev",1),("train2",4),("dev2",2)) for i in range(n)])
    batch([("experience5d",split,i,n) for split,n in (("train",4),("dev",1),("dev2",2)) for i in range(n)])
    call(("fit5d",))
    epochs=json.loads((dest/"evidence/fit.json").read_bytes())["shortlist"]
    batch([("battle5d","selection",f"epoch{ep}",0,1) for ep in epochs]);call(("select5d",))
    batch([("battle5d","confirm",a,i,n) for a in ("G2","G2search","high","V1","V2","V2low","V3","V3low")
           for n in (2 if a.startswith("V3") else 1,) for i in range(n)])
    for a in ("V2","V2low","V3low","V3"):call(("battle5d","cost",a,0,1))
    batch([("teacher5d",i,2,reference) for i in range(2) for reference in (0,1)])
    call(("audit5d",));call(("flips5d",));call(("verify5d",))
    call(("results5d",))
if __name__=="__main__":run(sys.argv[1])
