"""Rebuild both sides from the identified K6 host and pinned, instrumented HotKernel."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / "m1-infra1h"
sys.path.insert(0,str(OLD))
from build import edit, source_manifest
from campaign import sha

def build(family, production=False):
    parent = ROOT / "logs" / f"infra1h-{family}-kernel6"
    dest = ROOT / "logs/infra1h2" / (family+"-batch" if production else family)
    host_parent=ROOT/"logs"/f"infra1h-{family}-base2" if production else parent
    manifest = json.loads((host_parent/"build.json").read_bytes())
    for name, expected in manifest["artifacts"].items():
        if sha(host_parent/name) != expected:
            raise ValueError(name)
    locked=json.loads((OLD/"evidence/hosts.json").read_bytes())
    if manifest["artifacts"]!=locked[host_parent.name]["artifacts"] or source_manifest(host_parent/"host/Headless")!=locked[host_parent.name]["sources"]:
        raise ValueError("K6/base2 host identity mismatch")
    for name,digest in locked[parent.name]["adapter_sources"].items():
        if sha(parent/"plugin"/name)!=digest:raise ValueError(name)
    pinned = json.loads((ROOT/"logs/infra1h-hot-k2/manifest.json").read_bytes())
    if pinned["sha256"] != "87aa4c0775b2c60a733186adeb161e98ac23c0e9d0d5c542a5aed2781d0fd899":
        raise ValueError("Unexpected solver identity")
    solver = Path(pinned["solver"])
    if sha(solver) != pinned["sha256"]: raise ValueError(solver)
    host = dest/"host/Headless"
    plugin = dest/"plugin"
    for source,target in [(host_parent/"host/Headless",host),(parent/"plugin",plugin)]:
        target.mkdir(parents=True,exist_ok=True)
        for p in source.glob("*.cs"): shutil.copyfile(p,target/p.name)
        for p in source.glob("*.csproj"): (target/p.name).write_text(p.read_text().replace(str(parent),str(dest)).replace(str(host_parent),str(dest)))
    shutil.copytree(parent/"solver-bin",dest/"solver-bin",dirs_exist_ok=True)
    for name in ("Branch.cs","Slugs.cs"):shutil.copyfile(HERE/name,plugin/name)
    p=host/"IntegrationProbe.cs"
    anchor='if (command == "i1_infra1_reference_batch")'
    if production:
        bridge=(parent/"host/Headless/DrawWindows.cs").read_text(encoding="utf-8-sig").split("internal sealed partial class")[0]
        (host/"H2Bridge.cs").write_text(bridge)
    edit(p,anchor,'if (command == "i1_h2_branch") return new(){["type"]="h2.branch",["result"]=OfflineSearchHarness.HotBridge.Type("PublicBranch").GetMethod("Request")!.Invoke(null,new object[]{cmd})};\n        '+anchor)
    from private_fix import install
    install(plugin)
    feed=ROOT/"logs"/("infra0-profile-host" if family=="5d" else "infra0-world-profile")/"feed"
    env=os.environ|dict(DOTNET_CLI_HOME=str(dest/"cli"),NUGET_PACKAGES=str(dest/"packages"),DOTNET_NOLOGO="1")
    for project in [plugin/"adapter.csproj",host/"Sts2Headless.csproj"]:
        subprocess.run(["dotnet","build",project,"-c","Release" if project.parent==plugin else "Debug","--source",feed,"-p:NuGetAudit=false","--disable-build-servers","-m:1","-v:q"],check=True,env=env)
    output=host/"bin/Debug/net9.0/hot"
    output.mkdir(parents=True,exist_ok=True)
    for artifact in [solver,plugin/"bin/Release/net9.0/OfflineSearchHarness.dll"]:
        shutil.copyfile(artifact,output/artifact.name)
    (dest/"build.json").write_text(json.dumps(manifest|dict(artifacts={k:sha(dest/k) for k in manifest["artifacts"]},
        hot_artifacts={p.name:sha(p) for p in output.glob("*.dll")}),indent=2))
if __name__=="__main__":build(sys.argv[1], "--production" in sys.argv)
