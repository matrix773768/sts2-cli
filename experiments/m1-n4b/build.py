"""Expose only Nunchaku's current public attack count in the isolated N4 host."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-n4"))
from build_host import ROOT, sha

BASE=ROOT/"logs/n4-host-v2"
OUT=ROOT/"logs/n4b-host-v2"


def build(out):
    info=json.loads((BASE/"build.json").read_bytes())
    for name,value in info["artifacts"].items():
        if sha(BASE/name)!=value:
            raise ValueError(name)
    out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(BASE/"host",out/"host",ignore=shutil.ignore_patterns("bin","obj"))
    shutil.copytree(BASE/"solver-bin",out/"solver-bin")
    src=out/"host/Headless/NoslPublicEpisode.cs"
    code=src.read_text(encoding="utf-8-sig")
    anchor="            mechanism = new"
    method="    private object NoslTerminal(Node node)"
    if code.count(anchor)!=1 or code.count(method)!=1:
        raise ValueError("Unknown N4 public projection")
    helper="""    private int? PublicNunchakuCount(CombatPredictionSimulator sim)
    {
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var relic = combat.RelicsOf(_player).SingleOrDefault(r => r.Id.Entry == "NUNCHAKU");
        if (relic == null) return null;
        return combat.ReadRelicCounter(sim, relic) % 10;
    }
"""
    src.write_text(code.replace(method,helper+method).replace(anchor,"            nunchaku = PublicNunchakuCount(sim),\n"+anchor),encoding="utf8")
    subprocess.run(["dotnet","build",str(src.parent/"Sts2Headless.csproj"),"-p:NuGetAudit=false","--verbosity","quiet"],
        env=os.environ|dict(DOTNET_CLI_HOME=str(out),NUGET_PACKAGES=str(ROOT/"logs/nuget-packages")),check=True,timeout=180)
    info["sources"]["n4b_projection"]=sha(src)
    info["artifacts"]={k:sha(out/k) for k in info["artifacts"]}
    (out/"build.json").write_text(json.dumps(info,indent=2))


if __name__=="__main__":
    build(OUT)
