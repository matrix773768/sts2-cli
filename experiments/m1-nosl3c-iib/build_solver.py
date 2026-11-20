"""Build the isolated continuation bridge from the pinned Solver source."""
import argparse
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import json

HERE = Path(__file__).resolve().parent
E3 = runpy.run_path(str(HERE.parent / "m1-e3f/build_solver.py"))
ROOT, SOURCE, digest = (E3[k] for k in ("ROOT", "SOURCE", "digest"))
VERSION = "0.51.5-iib.1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    steam = Path.home() / "Desktop/STEAM/steamapps"
    parser.add_argument("--game-data", type=Path, default=steam / "common/Slay the Spire 2/data_sts2_windows_x86_64")
    parser.add_argument("--ritsu", type=Path, default=steam / "workshop/content/2868840/3747602295")
    args = parser.parse_args()
    output = args.output.resolve()
    if any(digest(p / "sts2.dll") != E3["GAME_HASH"] for p in (ROOT / "lib", args.game_data)):
        raise ValueError("Unexpected native game hash")
    if digest(SOURCE.parent / "baseline.dll") != E3["FROZEN_HASH"]:
        raise ValueError("Unexpected frozen Solver hash")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    shutil.copytree(SOURCE / "src", source / "src")
    shutil.copyfile(SOURCE / "CombatSolver.csproj", source / "CombatSolver.csproj")
    bridge = HERE / "InteractiveCombat.cs"
    shutil.copyfile(bridge, source / "src/Search/CombatBeamSolver.InteractiveCombat.cs")
    replay = source / "src/Search/CombatBeamSolver.Expansion.Replay.cs"
    old = "&& ShouldCaptureExecution(simulator, actions[0]) && simulator.BeginExecutionContinuationCapture();"
    code = replay.read_text(encoding="utf-8")
    if code.count(old) != 1:
        raise ValueError("Unexpected replay capture predicate")
    replay.write_text(code.replace(old, "&& (_interactiveCapture || ShouldCaptureExecution(simulator, actions[0]))"
                                   " && simulator.BeginExecutionContinuationCapture();"), encoding="utf-8")
    env = os.environ | {"DOTNET_CLI_HOME": str(ROOT / "logs/dotnet-home"),
                        "NUGET_PACKAGES": str(ROOT / "logs/nuget-packages")}
    subprocess.run(["dotnet", "build", str(source / "CombatSolver.csproj"), "-c", "Release",
                    "-p:CopyModOnBuild=false", "-p:OS=Unix", "-p:NuGetAudit=false",
                    f"-p:Sts2DataDir={args.game_data.resolve()}",
                    f"-p:RitsuWorkshopRoot={args.ritsu.resolve()}", f"-p:Version={VERSION}",
                    "-o", str(output / "bin")], env=env, check=True, timeout=150)
    (output / "build.json").write_text(json.dumps(dict(
        version=VERSION, source_revision=E3["REVISION"], patched_sha256=digest(output / "bin/CombatSolver.dll"),
        bridge_sha256=digest(bridge), game_sha256=E3["GAME_HASH"], frozen_sha256=E3["FROZEN_HASH"]),
        indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
