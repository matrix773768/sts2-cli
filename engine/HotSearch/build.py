"""Build a single HotKernel host from the frozen native initializer and rule binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = ROOT / "logs/hotsearch"
DLL = BUILD / "bin/Release/net9.0/OfflineSearchHarness.dll"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    locks = json.loads((ROOT / "experiments/m1-infra1h/evidence/hosts.json").read_bytes())
    source = ROOT / "logs/infra1h-5d-base2/host/Headless"
    if digest(ROOT/"lib/sts2.dll") != locks["hot-k2"]["game"]:
        raise ValueError("Game identity changed")
    BUILD.mkdir(parents=True, exist_ok=True)
    from kernel_build import kernel
    solver=kernel(HERE,ROOT,BUILD)
    project = ET.Element("Project", Sdk="Microsoft.NET.Sdk")
    props = ET.SubElement(project, "PropertyGroup")
    for k,v in dict(AssemblyName="OfflineSearchHarness", OutputType="Exe", TargetFramework="net9.0",
                    EnableDefaultCompileItems="false", ImplicitUsings="enable", Nullable="enable").items():
        ET.SubElement(props,k).text=v
    items = ET.SubElement(project, "ItemGroup")
    for name in ("RunSimulator.cs","SyntheticCombat.cs","RootWorker.cs","TargetMenu.cs"):
        path = source/name
        if digest(path) != locks["infra1h-5d-base2"]["sources"][name]:
            raise ValueError(path)
        if name == "SyntheticCombat.cs":
            # Only the native setup method, never the predictor snapshot/replay APIs.
            trimmed = path.read_text(encoding="utf-8-sig").split("    // The game serializes RNG")[0]
            path = BUILD/name
            path.write_text(trimmed+"}\n")
        ET.SubElement(items,"Compile", Include=str(path))
    for path in sorted(HERE.glob("*.cs")):
        ET.SubElement(items,"Compile",Include=str(path))
    for name in ("GodotSharp","sts2","SmartFormat","SmartFormat.ZString","Sentry","Steamworks.NET",
                 "MonoMod.Backports","MonoMod.ILHelpers","0Harmony","CombatSolver"):
        path = solver if name=="CombatSolver" else source/"bin/Debug/net9.0/GodotSharp.dll" if name=="GodotSharp" else ROOT/"lib"/(name+".dll")
        ET.SubElement(items,"Reference",Include=name,HintPath=str(path),Private=str(name in ("GodotSharp","CombatSolver")).lower())
    proj=BUILD/"HotSearch.csproj"
    ET.ElementTree(project).write(proj,encoding="utf-8")
    env=os.environ|dict(DOTNET_CLI_HOME=str(BUILD/"cli"),DOTNET_NOLOGO="1")
    subprocess.run(["dotnet","build",str(proj),"-c","Release","--source",str(ROOT/"logs/infra0-profile-host/feed"),
                    "-p:NuGetAudit=false","-v:q"],env=env,check=True)
    (BUILD/"identity.json").write_text(json.dumps(dict(host=digest(DLL),hot=digest(solver),
        game=digest(ROOT/"lib/sts2.dll")),indent=2))


if __name__=="__main__":
    build()
