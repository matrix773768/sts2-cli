"""Opt-in 1H entry points. Models, experience writers and actual world execution use CORE."""
import hashlib
import json
import os
from pathlib import Path
from campaign import ROOT

def select_host(task,world=False):
    if not world and task["kind"] not in ("natural","pairs"):return
    family="5e" if world else "5d"
    version="base2" if task["variant"] in ("h-scalar","h-batch") else task["variant"][2:].removesuffix("-g2")
    variable="STS2_CORE5E_WORLD" if world else "STS2_CORE5C_HOST"
    os.environ[variable]=str(ROOT/"logs"/f"infra1h-{family}-{version}")

def install(task,battle,pairs):
    if task["variant"].startswith(("h-kernel5","h-kernel6")) and "folder" in task:
        here=Path(__file__).resolve().parent
        paths=[here/name for name in ("integration.py","frontier_model.py","conditional_model.py","exact_model.py","guarded_model.py")]
        paths.extend(ROOT/"experiments"/name for name in ("m1-core5c/complete.py","m1-core5c/policy5c.py","m1-core4/semantic.py","m1-infra0/worker.py","m1-infra0/world_measure.py"))
        manifests={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        (Path(task["folder"])/"runtime-identity.json").write_text(json.dumps(manifests,indent=2))
    if task["variant"]=="h-scalar":return None
    import sys
    sys.path.insert(0,str(ROOT/"experiments/m1-infra1a"))
    import execution
    if task["variant"]=="h-batch":return execution.install(task,battle,pairs)
    import frontier_model
    observer=frontier_model.install(task,battle)
    if os.environ.get('INFRA1H_FAIR')=='1':
        import fair
        return fair.install(task)
    return observer
