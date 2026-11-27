"""Run frozen HotDraw assertions with the newly patched solver, and original CORE mechanisms."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from campaign import HERE,ROOT,LOG,E,sha

def hot():
    active=json.loads((ROOT/"logs/infra1h-hot-k2/manifest.json").read_bytes())
    parent=json.loads((ROOT.parent/"sts2-cli/logs/hotdraw-structures-build-03/build.json").read_bytes())
    old=Path(parent["dll"])
    assert sha(old)==parent["harness_sha256"] and sha(Path(active["solver"]))==active["sha256"]
    out=LOG/"hot-regression";out.mkdir()
    dll=out/old.name
    shutil.copyfile(old,dll)
    shutil.copyfile(old.with_suffix(".deps.json"),dll.with_suffix(".deps.json"))
    config=json.loads(old.with_suffix(".runtimeconfig.json").read_bytes())
    config["runtimeOptions"]["configProperties"]["CombatSolverDll"]=active["solver"]
    dll.with_suffix(".runtimeconfig.json").write_text(json.dumps(config))
    sys.path.insert(0,str(HERE.parent/"hotdraw"))
    from check import fixtures
    scenarios=fixtures(Path(active["solver"]).parents[5])
    receipt={}
    for name in ("known","draws","shuffle_multi","turn","plain","unsupported","nested","exhaust","order"):
        case=out/name;case.mkdir()
        request=case/"request.json";request.write_text(json.dumps(scenarios[name]))
        result=case/"result.json"
        subprocess.run([parent["runtime"],dll,"--hotdraw",name,request,result],cwd=case,check=True,timeout=75)
        receipt[name]=json.loads(result.read_bytes())
    with gzip.open(E/"hot-regression.json.gz","wt",encoding="utf8") as f:json.dump(receipt,f)

def core(version):
    out=LOG/("core-regression-"+version+"-"+str(os.getpid()));out.mkdir()
    (out/"evidence").mkdir()
    shutil.copyfile(HERE.parent/"m1-core5d/evidence/panel.gz",out/"evidence/panel.gz")
    os.environ["STS2_CORE5C_HOST"]=str(ROOT/"logs"/("infra1h-5d-"+version))
    os.environ["STS2_CORE5D_RUN"]=str(out)
    sys.path.insert(0,str(HERE.parent/"m1-core5d"))
    import battle5d,audit5d,mechanisms5c
    import integration
    task=dict(variant="h-"+version,kind="natural")
    integration.install(task,battle5d,None)
    mechanisms5c.E=mechanisms5c.OUT=out
    mechanisms5c.run()
    cases=json.loads((out/"mechanisms.json").read_bytes())["cases"]
    assert cases==json.loads((HERE.parent/"m1-core5c/evidence/mechanisms.json").read_bytes())["cases"]
    host,g2,net,plan=battle5d.configure(out,"V2low")
    lane=battle5d.Lane(host,0)
    try:checks=dict(cases=audit5d.cases(lane,g2,net,plan),relic=audit5d.relic(lane,plan))
    finally:lane.close();host.close()
    frozen=json.loads((HERE.parent/"m1-core5d/evidence/audit.json").read_bytes());frozen.pop("seconds")
    from semantic_check import digest
    assert digest(frozen)==digest(checks)
    (E/("core-regression-"+version+".json")).write_text(json.dumps(dict(mechanisms=list(cases),semantic_sha256=digest(checks),version=version),indent=2))

if __name__=="__main__":
    if sys.argv[1]=="hot":hot()
    else:
        sys.path.append(str(HERE.parent/"m1-infra0"))
        core(sys.argv[1])
