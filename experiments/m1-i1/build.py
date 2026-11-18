from pathlib import Path
import shutil
import subprocess
import os
import hashlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = ROOT / "logs/m1-i1-build"
SOLVER = ROOT.parent / "CombatSolver-m1-cs1/baseline.dll"

def build():
    if hashlib.sha256(SOLVER.read_bytes()).hexdigest() != "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13":
        raise ValueError("Unexpected CombatSolver DLL")
    src = BUILD / "Headless"
    src.mkdir(parents=True, exist_ok=True)
    for name, dest in [("Sts2Headless", src), ("GodotStubs", BUILD / "GodotStubs")]:
        dest.mkdir(exist_ok=True)
        for file in (ROOT / "src" / name).iterdir():
            if file.suffix in {".cs", ".csproj"}:
                shutil.copyfile(file, dest / file.name)
    core = BUILD / "GodotStubs/Core.cs"
    code = core.read_text(encoding="utf-8")
    anchor = "public class Node : GodotObject\n{"
    assert code.count(anchor) == 1
    core.write_text(code.replace(anchor, anchor + """
    public Collections.Array<Node> FindChildren(string pattern, string type, bool recursive, bool owned) => new();
""") + "\npublic static class DisplayServer { public static string GetName() => \"headless\"; }\n", encoding="utf-8")
    project = src / "Sts2Headless.csproj"
    code = project.read_text(encoding="utf-8").replace("..\\..\\lib\\", str(ROOT / "lib") + "/")
    project.write_text(code.replace("</Project>", f"""
    <PropertyGroup><AssemblyName>OfflineSearchHarness</AssemblyName></PropertyGroup>
    <ItemGroup><Reference Include="CombatSolver" HintPath="{SOLVER}" Private="false" /></ItemGroup>
</Project>"""), encoding="utf-8")
    program = src / "Program.cs"
    code = program.read_text(encoding="utf-8")
    anchor = "result = HandleCommand(sim, cmd);"
    assert code.count(anchor) == 1
    program.write_text(code.replace(anchor,
        'result = cmd.GetProperty("cmd").GetString()?.StartsWith("i1_", StringComparison.Ordinal) == true ? IntegrationProbe.Run(sim, cmd) : HandleCommand(sim, cmd);'),
        encoding="utf-8")
    simulator = src / "RunSimulator.cs"
    code = simulator.read_text(encoding="utf-8")
    anchor = "public class RunSimulator"
    assert code.count(anchor) == 1
    simulator.write_text(code.replace(anchor, "public partial class RunSimulator"), encoding="utf-8")
    shutil.copyfile(HERE / "IntegrationProbe.cs", src / "IntegrationProbe.cs")
    env = {**os.environ, "DOTNET_CLI_HOME": str(ROOT / "logs/dotnet-home"),
           "NUGET_PACKAGES": str(ROOT / "logs/nuget-packages")}
    subprocess.run(["dotnet", "build", str(project), "-p:NuGetAudit=false"], check=True, env=env, timeout=60)

if __name__ == "__main__":
    build()
