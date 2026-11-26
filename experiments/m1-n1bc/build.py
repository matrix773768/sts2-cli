"""Extend the public episode and search graph at their shared projection point."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "logs/m1-sv4a-host"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out):
    info = json.loads((BASE / "build.json").read_bytes())
    for name, expected in info["artifacts"].items():
        if sha(BASE / name) != expected:
            raise ValueError(name)
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(BASE / "host", out / "host", ignore=shutil.ignore_patterns("bin", "obj"))
    shutil.copytree(BASE / "solver-bin", out / "solver-bin")
    src = out / "host/Headless/NoslPublicEpisode.cs"
    original = src.read_text(encoding="utf-8-sig")
    anchor = '            schema = "sts2.nosl_observation.v3",'
    if original.count(anchor) != 1:
        raise ValueError("Unexpected host source")
    insert = (Path(__file__).with_name("projection.cs.inc")).read_text(encoding="utf-8")
    src.write_text(original.replace(anchor, anchor + "\n" + insert), encoding="utf-8")
    env = os.environ | {"DOTNET_CLI_HOME": str(out), "NUGET_PACKAGES": str(ROOT/"logs/nuget-packages")}
    subprocess.run(["dotnet", "build", str(src.parent/"Sts2Headless.csproj"), "-p:NuGetAudit=false"],
                   env=env, check=True, timeout=150)
    info["sources"]["pilot_projection"] = sha(src)
    info["artifacts"] = {p: sha(out/p) for p in info["artifacts"]}
    (out/"build.json").write_text(json.dumps(info, indent=2))


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve())
