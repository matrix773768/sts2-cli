"""Run after campaign.py high. Groups share the same append-only actual-cost ledger."""
import json
import subprocess
import sys
import time
from campaign import HERE,ROOT,RUNS,charge,ledger,treatment
from semantic_check import compare

def finish():
    entries=ledger()
    if len(entries)<4 or not all(r["success"] for r in entries[:4]):
        raise RuntimeError("Complete and validate the 5D high block first")
    def run_new(kind,mode,arm="V2",n=1,smoke=False,occurrence=1):
        matches=[r for r in ledger() if (r.get("kind"),r.get("mode"),r.get("arm"),r.get("n"),r.get("smoke"))==(kind,mode,arm,n,smoke)]
        if len([r for r in matches if r["success"]])>=occurrence:return True
        if any(not r["success"] for r in matches):raise RuntimeError(f"Inspect prior failure: {matches[-1]['tag']}")
        return treatment(kind,mode,arm,n,smoke)
    build=ROOT/"logs/infra0-world-profile/build.json"
    if not build.exists():
        start=time.perf_counter()
        result=subprocess.run([sys.executable,"-B",str(HERE/"build_meter.py"),str(ROOT.parent/"sts2-cli"),"--world"],cwd=ROOT)
        charge(dict(kind="build",worker_s=time.perf_counter()-start,success=result.returncode==0))
        result.check_returncode()
    check=[]
    for mode in ("baseline","aggregate"):
        if not run_new("initial-train",mode,smoke=True):return
        check.append(next(r for r in ledger() if r.get("smoke") and r["mode"]==mode and r["success"]))
    report=compare(*(RUNS/r["tag"] for r in check))
    (RUNS/"infra0b-world-check.json").write_text(json.dumps(report))
    for kind in ("initial-train","initial-dev","audit"):
        for mode in ("baseline","aggregate"):
            if not run_new(kind,mode):return
    # Cover all distinct resource configurations before spending on second passes.
    for mode in ("baseline","aggregate"):
        if not run_new("natural",mode,"V2low"):return
    for n in (2,4):
        if not run_new("natural","baseline",n=n):return
    for kind,arm in (("natural","V2"),("pairs","V2"),("initial-train","V2"),("initial-dev","V2"),("natural","V2low")):
        for mode in ("aggregate","baseline"):
            run_new(kind,mode,arm,occurrence=2)

if __name__=="__main__":finish()
