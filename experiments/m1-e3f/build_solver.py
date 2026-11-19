"""Build the E3F solver in an isolated source tree, with deployment disabled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REVISION = "78e4545e825e58c3d999354b1ffcd54241b1d2cf"
SOURCE = ROOT.parent / "CombatSolver-m1-cs1" / f"CombatSolver-{REVISION}"
VERSION = "0.51.5-e3f.1"
GAME_HASH = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"
FROZEN_HASH = "d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    steam = Path.home() / "Desktop/STEAM/steamapps"
    parser.add_argument("--game-data", type=Path, default=steam /
                        "common/Slay the Spire 2/data_sts2_windows_x86_64")
    parser.add_argument("--ritsu", type=Path, default=steam / "workshop/content/2868840/3747602295")
    args = parser.parse_args()
    output = args.output.resolve()
    if digest(args.game_data / "sts2.dll") != GAME_HASH or digest(ROOT / "lib/sts2.dll") != GAME_HASH:
        raise ValueError("Expected the frozen native game build")
    if digest(SOURCE.parent / "baseline.dll") != FROZEN_HASH:
        raise ValueError("Unexpected frozen solver")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    shutil.copytree(SOURCE / "src", source / "src")
    shutil.copyfile(SOURCE / "CombatSolver.csproj", source / "CombatSolver.csproj")
    patch = HERE / "predator.patch"
    env = os.environ | {"DOTNET_CLI_HOME": str(ROOT / "logs/dotnet-home"),
                        "NUGET_PACKAGES": str(ROOT / "logs/nuget-packages"),
                        "GIT_CEILING_DIRECTORIES": str(output)}
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, env=env, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, env=env, check=True)
    subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                   cwd=source, env=env, check=True)
    subprocess.run(["dotnet", "build", str(source / "CombatSolver.csproj"), "-c", "Release",
                    "-p:CopyModOnBuild=false", "-p:OS=Unix", "-p:NuGetAudit=false",
                    f"-p:Sts2DataDir={args.game_data.resolve()}",
                    f"-p:RitsuWorkshopRoot={args.ritsu.resolve()}", f"-p:Version={VERSION}",
                    "-o", str(output / "bin")], env=env, check=True, timeout=150)
    dll = output / "bin/CombatSolver.dll"
    (output / "build.json").write_text(json.dumps(dict(
        version=VERSION, source_revision=REVISION, patched_sha256=digest(dll),
        source_patch_sha256=digest(patch), game_sha256=GAME_HASH, frozen_sha256=FROZEN_HASH),
        indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
