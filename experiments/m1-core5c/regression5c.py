"""Run the existing CORE boundary, model and full-loop suites in isolated Python processes."""
import json,subprocess,sys
import os
from time import perf_counter
from pathlib import Path
HERE=Path(__file__).resolve().parent
def run():
    result={}
    for folder in ("m1-core1r2","m1-core2","m1-core3","m1-core4","m1-core5a","m1-core5b","m1-core5c"):
        start=perf_counter()
        p=subprocess.run([sys.executable,"-m","unittest","discover","-s",str(HERE.parent/folder),"-p","test*.py"],cwd=HERE.parents[1],
                         capture_output=True,text=True,encoding="utf8",errors="replace")
        result[folder]=dict(status=p.returncode,seconds=perf_counter()-start,summary=p.stderr[-2500:])
    dest=Path(os.environ.get("STS2_CORE5C_RUN",HERE))
    (dest/"evidence/regression.json").write_text(json.dumps(result,indent=2))
    if any(s["status"] for s in result.values()):
        raise SystemExit(1)
if __name__=="__main__":
    run()
