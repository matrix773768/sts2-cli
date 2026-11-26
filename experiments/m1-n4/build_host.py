"""Isolate the N1BC host, retaining its exact solver. Intervene only before the first observation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT/"logs/n1bc-host"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out):
    info = json.loads((BASE/"build.json").read_bytes())
    for name, value in info["artifacts"].items():
        if sha(BASE/name) != value:
            raise ValueError(name)
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(BASE/"host", out/"host", ignore=shutil.ignore_patterns("bin","obj"))
    shutil.copytree(BASE/"solver-bin", out/"solver-bin")
    src = out/"host/Headless/SyntheticCombat.cs"
    code = src.read_text(encoding="utf-8-sig")
    anchor = "        return DetectDecisionPoint();"
    if code.count(anchor) != 1:
        raise ValueError("Unknown synthetic root contract")
    src.write_text(code.replace(anchor,(HERE/"opening.cs.inc").read_text()+ "\n"+anchor),encoding="utf-8")
    subprocess.run(["dotnet","build",str(src.parent/"Sts2Headless.csproj"),"-p:NuGetAudit=false"],
        env=os.environ | dict(DOTNET_CLI_HOME=str(out), NUGET_PACKAGES=str(ROOT/"logs/nuget-packages")),
        check=True, timeout=180)
    info["sources"]["n4_opening"]=sha(src)
    info["artifacts"]={k:sha(out/k) for k in info["artifacts"]}
    (out/"build.json").write_text(json.dumps(info,indent=2))


if __name__=="__main__":
    build(Path(sys.argv[1]).resolve())
