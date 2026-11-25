from contextlib import closing
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,str(Path.cwd()))
from tools.training_manager import recovery
from tools.training_manager.common import ROOT, HOME, checksum, freeze, read, write
from tools.training_manager.dashboard.backend import Backend
from tools.training_manager.ledger import identity, snapshot
from tools.training_manager.manager import Manager

formal=Manager(HOME)
with closing(formal.db):
    proof, original, source=recovery.admitted(formal)
    recovery.verify_compatibility(original,proof)
    template,_=recovery.offer(formal)
    assert template["stages"][1]["id"]=="g3-direct"
    assert template["stages"][-1]["id"]=="g12-audit"
    assert template["limits"]["confirmation_evaluations"]==0
    assert template["limits"]==original["limits"]
    assert "budget_seconds" not in template
    assert len(template["stages"])==91
    before=checksum(source/"report.json")
    backend=Backend(HOME)
    recovered=next(p for p in backend.plans(formal) if p["spec"]["id"]==proof["key"])
    assert not recovered["reasons"]
    try: backend.action(formal,"freeze",{"id":proof["key"]},"test")
    except ValueError as exc: assert "另行批准" in str(exc)
    else: raise AssertionError("budgetless freeze")

home=HOME/f"inf3-smoke-{uuid.uuid4().hex[:8]}"
queue=Manager(home)
queue.control("mode","Full")
output=home/"jobs/inf3-probe"
test=template["stages"][1]
args=list(test["args"])
args[args.index("--target")+1]="964"
plan=dict(id=output.name,name="INF3 four-root validation",type="smoke",cwd=".",mode="Any",max_retries=0,
          python=original["python"],output=output.relative_to(ROOT).as_posix(),budget_seconds=300,
          inputs=[],stages=[test|dict(args=args,depends_on=[])])
queue.submit(freeze(plan,home))

def probe(*_):
    return dict(ram_mb=99999,disk_mb=99999,ac=True,idle_seconds=999,gpus=[])

try:
    recovery.restore_artifacts(proof,source,output)
    recovery.restore_artifacts(proof,source,output)
    check=output/"g3-direct/ledger/results.sqlite"
    assert identity(check)==proof["g3"]["identity"]
    with snapshot(check) as db:
        prior=db.execute("SELECT ordinal,sha FROM results ORDER BY ordinal").fetchall()
    finish=time.monotonic()+300
    while time.monotonic()<finish:
        queue.step(probe)
        job=queue.job(output.name)
        if job["state"] not in ("queued","running","pausing"): break
        time.sleep(.18)
    report=queue.report(job,persist=False)
    assert job["state"]=="completed", report
    assert [r["stage"] for r in report["runs"]]==["g3-direct"]
    with snapshot(check) as db:
        after=db.execute("SELECT ordinal,sha FROM results ORDER BY ordinal").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone()==("ok",)
    assert after[:960]==prior and [r[0] for r in after[960:]]==[960,961,962,963]
    assert identity(check)["contract"]==proof["g3"]["identity"]["contract"]
    assert checksum(source/"report.json")==before
    assert all(checksum(source/name)==value for name,value in proof["files"].items())
    data=dict(queue=home.relative_to(ROOT).as_posix(),old=960,new=4,total=len(after),seconds=report["seconds"],
              original_report_sha256=before, committed_sha_unchanged=True,head=report["spec"]["baseline"])
    write(HOME/"inf3-forensics/real-smoke.json",data)
    print(data,flush=True)
finally:
    job=queue.job(output.name)
    if job["state"] == "queued":
        queue.request(output.name,"cancel")
    if job["state"] in ("running","pausing"):
        queue.request(output.name,"force")
        while queue.job(output.name)["state"] in ("running","pausing"):
            queue.step(probe)
            time.sleep(.2)
    for child in queue.children:
        child.wait(timeout=15)
