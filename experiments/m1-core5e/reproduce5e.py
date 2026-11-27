"""Rebuild from frozen local 5D assets into an empty destination. The sealed evidence is read-only."""
import gzip,json,os,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
def reproduce(destination):
    here=Path(__file__).resolve().parent;root=here.parents[1]
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=False)
    ev=dest/"evidence";world=dest/"world-host"
    env=os.environ|{"STS2_CORE5E_RUN":str(dest),"STS2_CORE5E_WORLD":str(world)}
    def call(job):
        script,*args=job
        subprocess.run([sys.executable,str(here/(script+".py")),*map(str,args)],cwd=root,env=env,check=True)
    def batch(jobs):
        with ThreadPoolExecutor(max_workers=4) as workers:list(workers.map(call,jobs))
    call(("panel5e",));call(("host5e",world))
    batch([("conditions5e",s,i,n) for s,n in (("train",4),("dev",2)) for i in range(n)])
    call(("transitions5e",));call(("fit5e",));call(("reliability5e",))
    batch([("battle5e","selection",arm,0,1) for arm in ("mc","td","V2")])
    call(("confirm5e",))
    challenger=json.loads((ev/"selection.json").read_bytes())["challenger"]
    batch([("battle5e","confirm",arm,0,1) for arm in ("V2","V2low")])
    arms=("V2",challenger,"V2low")
    bad=set()
    for arm in arms:
        for f in ev.glob("confirm-"+arm+"-*.gz"):
            with gzip.open(f) as stream:
                bad.update(r["i"] for r in map(json.loads,stream) if not r["terminal"])
    if bad:batch([("repair5e",arm,*sorted(bad)) for arm in arms])
    batch([("conditions5e","train",i,2,1) for i in range(2)])
    call(("costnative5e",))
    for script in ("known5e","verify5e","checks5e","report5e","ledger5e"):call((script,))
if __name__=="__main__":reproduce(sys.argv[1])
