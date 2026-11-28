"""Build a separate, native-only replay executable with a pre-reward gold observation."""
from pathlib import Path
import subprocess
import os
import json
from xml.etree import ElementTree as ET
from build import BUILD,HERE,ROOT,digest


def build():
    dest=BUILD/"oracle";dest.mkdir(exist_ok=True)
    base=ROOT/"logs/infra1h-5d-base2/host/Headless"
    locks=json.loads((ROOT/"experiments/m1-infra1h/evidence/hosts.json").read_bytes())["infra1h-5d-base2"]["sources"]
    project=ET.parse(BUILD/"HotSearch.csproj")
    items=project.find("ItemGroup")
    for node in list(items):
        if node.tag=="Compile" or node.get("Include")=="CombatSolver":items.remove(node)
    def include(path):ET.SubElement(items,"Compile",Include=str(path))
    def stage(name,body):
        path=dest/name;path.write_text(body);include(path)
    for name in ("SyntheticCombat.cs","RunSimulator.cs","TargetMenu.cs","RootWorker.cs"):
        path=base/name
        if digest(path)!=locks[name]:raise ValueError(path)
        body=path.read_text(encoding="utf-8-sig")
        if name=="SyntheticCombat.cs":
            stage(name,body.split("    // The game serializes RNG")[0].replace("using CombatSolver;","")+"}")
        elif name=="RunSimulator.cs":
            for anchor,replace in [
                ("public partial class RunSimulator\n{","public partial class RunSimulator\n{\n    internal object? BeforeRewards;"),
                ('["can_play"] = c.CanPlay','["upgraded"] = c.IsUpgraded, ["can_play"] = c.CanPlay'),
                ('Log($"Post-combat:','BeforeRewards ??= new{hp=player.Creature.CurrentHp,max_hp=player.Creature.MaxHp,gold=player.Gold};\n        Log($"Post-combat:')]:
                if body.count(anchor)!=1:raise ValueError(anchor)
                body=body.replace(anchor,replace)
            stage(name,body)
        else:include(path)
    prefix=(HERE/"Program.cs").read_text(encoding="utf-8-sig").split("    [System.Runtime.CompilerServices.MethodImpl")[0]
    stage("Program.cs",prefix.replace("        Serve();","        Native.Serve();")+"}")
    include(HERE/"audit/Native.cs")
    proj=dest/"Native.csproj";project.write(proj,encoding="utf-8")
    subprocess.run(["dotnet","build",str(proj),"-c","Release","--source",str(ROOT/"logs/infra0-profile-host/feed"),
        "-p:NuGetAudit=false","-v:q"],env=os.environ|dict(DOTNET_CLI_HOME=str(BUILD/"cli")),check=True)


if __name__=="__main__":build()
