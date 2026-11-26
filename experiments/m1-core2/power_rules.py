"""Ask the existing N1A exporter for named power hooks present in development C."""
from state import *
import subprocess
from time import perf_counter
from hashlib import sha256

def run(out,records):
    out.mkdir(parents=True,exist_ok=False)
    t=perf_counter()
    root=HERE.parents[1]/"logs"
    identity=json.loads((root/"hotdraw-mechanism-build-03/build.json").read_bytes())
    for k,label in (("dll","harness"),("solver","solver"),("runtime","runtime")):
        assert sha256(Path(identity[k]).read_bytes()).hexdigest()==identity[label+"_sha256"]
    wanted={"DEMON_FORM_POWER"}
    for b in batches(records):
        for r in b:
            if r["source"]=="natural":wanted.update(p["id"] for p in r["features"]["state"]["powers"])
    req=json.loads((root/"hotdraw-mechanism-final/TEST_SUBJECT_BOSS/request.json").read_bytes())
    req.update(powers=[dict(powerId=id,target="Player",amount=1) for id in sorted(wanted)])
    file=out/"request.json"
    file.write_text(json.dumps(req))
    subprocess.run([identity["runtime"],identity["dll"],"--hotdraw","mechanisms",str(file.resolve()),str((out/"export.json").resolve())],
        cwd=root/"hotdraw-mechanism-build-03"/("CombatSolver-"+identity["upstream"]),check=True,timeout=60)
    (out/"seconds.json").write_text(json.dumps(perf_counter()-t))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
