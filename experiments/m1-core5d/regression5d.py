"""Keep each historical suite's module imports isolated."""
import json,subprocess,sys,time,re
from pathlib import Path
from panel5d import E,ROOT
def run():
    results={}
    for name in ("m1-core1r2","m1-core2","m1-core3","m1-core4","m1-core5a","m1-core5b","m1-core5c","m1-core5d"):
        start=time.perf_counter()
        r=subprocess.run([sys.executable,"-m","unittest","discover","-s","experiments/"+name],cwd=ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors="replace")
        results[name]=dict(exit=r.returncode,seconds=time.perf_counter()-start,output=r.stdout[-3000:])
    (E/"tests.json").write_text(json.dumps(results,indent=2))
    if any(v["exit"] for v in results.values()):raise SystemExit(1)
if __name__=="__main__":run()
