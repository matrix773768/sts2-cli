"""Build a separate, native-only replay executable with a pre-reward gold observation."""
from pathlib import Path
import subprocess
import os
import json
from xml.etree import ElementTree as ET
from build import BUILD,HERE,ROOT,digest


def build():
    dest=Path(os.environ.get("HOTSEARCH_ORACLE_DIR",BUILD/"oracle"));dest.mkdir(exist_ok=True,parents=True)
    base=ROOT/"logs/infra1h-5d-base2/host/Headless"
    locks=json.loads((ROOT/"experiments/m1-infra1h/evidence/hosts.json").read_bytes())["infra1h-5d-base2"]["sources"]
    project=ET.parse(BUILD/"HotSearch.csproj")
    items=project.find("ItemGroup")
    for node in list(items):
        if node.tag=="Compile" or node.get("Include")=="CombatSolver":items.remove(node)
    if os.environ.get("HOTSEARCH_ORACLE_MATH")=="1":
        # Rebuild the offline Godot API in isolation for native PhantasmalGardener.EnlargeMove.
        stub=dest/"godot";stub.mkdir(exist_ok=True)
        source=ROOT/"src/GodotStubs"
        for p in [*source.glob("*.cs"),source/"GodotStubs.csproj"]:
            body=p.read_text(encoding="utf-8-sig")
            if p.name=="Math.cs":
                anchor="    public const float Pi = MathF.PI;"
                if body.count(anchor)!=1:raise ValueError(anchor)
                body=body.replace(anchor,anchor+"\n    public static float Log(float value) => MathF.Log(value);")
            if os.environ.get("HOTSEARCH_ORACLE_SCENE")=="1":
                changes={
                    "UI.cs":[("public class CanvasItem : Node\n{","public class CanvasItem : Node\n{\n    public void SetVisible(bool visible) => Visible=visible;")],
                    "Core.cs":[("    public Node? GetParent() => _parent;", """    private InternalMode _siblingMode;
    public int GetIndex(bool includeInternal = false)
    {
        if (_parent == null) return -1;
        var siblings = _parent._children;
        if (siblings.Any(node => node._siblingMode != InternalMode.Disabled))
            throw new NotSupportedException("native/internal scene sibling order");
        return siblings.IndexOf(this);
    }
    public Node? GetParent() => _parent;"""),
                        ("        _children.Add(child);","        child._siblingMode = mode;\n        _children.Add(child);")]}
                for anchor,replacement in changes.get(p.name,[]):
                    if body.count(anchor)!=1:raise ValueError(anchor)
                    body=body.replace(anchor,replacement)
            (stub/p.name).write_text(body,encoding="utf-8")
        subprocess.run(["dotnet","build",str(stub/"GodotStubs.csproj"),"-c","Release","--source",
            str(ROOT/"logs/infra0-profile-host/feed"),"-p:NuGetAudit=false","-v:q"],
            env=os.environ|dict(DOTNET_CLI_HOME=str(BUILD/"cli")),check=True)
        ref=items.find("Reference[@Include='GodotSharp']")
        ref.set("HintPath",str(stub/"bin/Release/net9.0/GodotSharp.dll"))
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
    include(HERE/"audit/Resample.cs")
    include(HERE/"audit/DrawCut.cs")
    proj=dest/"Native.csproj";project.write(proj,encoding="utf-8")
    subprocess.run(["dotnet","build",str(proj),"-c","Release","--source",str(ROOT/"logs/infra0-profile-host/feed"),
        "-p:NuGetAudit=false","-v:q"],env=os.environ|dict(DOTNET_CLI_HOME=str(BUILD/"cli")),check=True)


if __name__=="__main__":build()
