"""Rerun affected historical suites in separate processes to isolate their import paths."""
import json,subprocess,sys,time
from panel5e import E,ROOT
def run():
    report={}
    for name in ("m1-core4","m1-core5b","m1-core5c","m1-core5d","m1-core5e"):
        t=time.perf_counter()
        result=subprocess.run([sys.executable,"-m","unittest","discover","-s","experiments/"+name],
                              cwd=ROOT,text=True,errors="replace",stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        report[name]=dict(exit=result.returncode,output=result.stdout,seconds=time.perf_counter()-t)
    (E/"tests.json").write_text(json.dumps(report,indent=2))
    if any(r["exit"] for r in report.values()):raise SystemExit(1)
if __name__=="__main__":run()
