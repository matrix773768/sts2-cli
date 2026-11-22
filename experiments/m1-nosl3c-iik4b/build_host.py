"""Stage a new II-H.7 host bundle with the shared stub ABI fixes."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "logs/m1-nosl3c-iih7-host"
HOST_BIN = Path("Headless/bin/Debug/net9.0")

if __name__ == "__main__":
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True)
    stubs = output / "GodotStubs"
    shutil.copytree(ORIGINAL / "GodotStubs", stubs, ignore=shutil.ignore_patterns("bin", "obj"))
    core = (ROOT / "src/GodotStubs/Core.cs").read_text(encoding="utf-8")
    # Keep the separately staged II-H.7 host's two existing Core additions.
    core = core.replace("    public enum InternalMode",
                        "    public Collections.Array<Node> FindChildren(string pattern, string type, bool recursive, bool owned) => new();\n\n"
                        "    public enum InternalMode", 1)
    core += '\npublic static class DisplayServer { public static string GetName() => "headless"; }\n'
    (stubs / "Core.cs").write_text(core, encoding="utf-8")
    shutil.copy2(ROOT / "src/GodotStubs/Types.cs", stubs / "Types.cs")
    start = perf_counter()
    subprocess.run(["dotnet", "build", str(stubs / "GodotStubs.csproj"), "--nologo", "-p:NuGetAudit=false"], check=True, cwd=ROOT,
                   env=os.environ | {"DOTNET_CLI_HOME": str(output / "dotnet-cli"),
                                     "NUGET_PACKAGES": str(ROOT / "logs/nuget-packages")})
    seconds = perf_counter() - start
    dest = output / HOST_BIN
    shutil.copytree(ORIGINAL / HOST_BIN, dest)
    for filename in ("GodotSharp.dll", "GodotSharp.pdb"):
        shutil.copy2(stubs / "bin/Debug/net9.0" / filename, dest / filename)
    data = dict(version="II-K.4B", compile_seconds=seconds, artifacts={
        name: dict(path=str(dest / name), sha256=sha256((dest / name).read_bytes()).hexdigest())
        for name in ("OfflineSearchHarness.dll", "GodotSharp.dll")
    })
    (output / "build.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data))
