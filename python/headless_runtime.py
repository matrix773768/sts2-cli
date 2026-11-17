"""Select the .NET host for an already-built headless engine."""

import os
from pathlib import Path
import re
import shutil


ENGINE = (Path(__file__).resolve().parents[1]
          / "src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll")


def headless_command():
    """Use a .NET 9 runtime without involving the build SDK."""
    configured_host = os.environ.get("STS2_DOTNET")
    if configured_host is not None:
        host = Path(configured_host).expanduser()
        if not configured_host or not host.is_file():
            raise RuntimeError(f"STS2_DOTNET must point to a dotnet executable: {configured_host!r}")
        executable = str(host.resolve())
    else:
        name = "dotnet.exe" if os.name == "nt" else "dotnet"
        candidates = (Path.home() / directory / name for directory in (".dotnet-arm64", ".dotnet"))
        executable = next((str(path) for path in candidates if path.is_file()), None)
        executable = executable or shutil.which(name)
        if executable is None:
            raise RuntimeError("No dotnet host found. Set STS2_DOTNET to a host with .NET 9.")

    version = os.environ.get("STS2_DOTNET_VERSION")
    if version is not None:
        if not re.fullmatch(r"9\.0\.[0-9]+", version):
            raise RuntimeError("STS2_DOTNET_VERSION must specify a .NET 9 patch version (9.0.x).")
        return [executable, "exec", "--fx-version", version, str(ENGINE)]
    return [executable, "exec", "--roll-forward", "LatestPatch", str(ENGINE)]
