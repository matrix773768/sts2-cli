"""The headless host can be selected without probing the SDK or game DLLs."""

from pathlib import Path

import pytest

import headless_runtime


def test_explicit_host_and_patch(monkeypatch, tmp_path):
    host = tmp_path / "isolated host" / "dotnet"
    host.parent.mkdir()
    host.touch()
    monkeypatch.setenv("STS2_DOTNET", str(host))
    monkeypatch.setenv("STS2_DOTNET_VERSION", "9.0.7")

    assert headless_runtime.headless_command() == [
        str(host.resolve()), "exec", "--fx-version", "9.0.7", str(headless_runtime.ENGINE),
    ]


def test_missing_explicit_host_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("STS2_DOTNET", str(tmp_path / "missing-dotnet"))
    monkeypatch.setattr(headless_runtime.shutil, "which", lambda name: pytest.fail("host fallback"))

    with pytest.raises(RuntimeError, match="STS2_DOTNET"):
        headless_runtime.headless_command()


@pytest.mark.parametrize("version", ["10.0.15", "9.1.0", "9.0", "", "9.0.7-preview"])
def test_explicit_version_must_be_a_net9_patch(monkeypatch, tmp_path, version):
    host = tmp_path / "dotnet"
    host.touch()
    monkeypatch.setenv("STS2_DOTNET", str(host))
    monkeypatch.setenv("STS2_DOTNET_VERSION", version)

    with pytest.raises(RuntimeError, match="STS2_DOTNET_VERSION"):
        headless_runtime.headless_command()


def test_default_host_limits_roll_forward_to_patches(monkeypatch, tmp_path):
    monkeypatch.delenv("STS2_DOTNET", raising=False)
    monkeypatch.delenv("STS2_DOTNET_VERSION", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(headless_runtime.shutil, "which", lambda name: "system-dotnet")

    assert headless_runtime.headless_command() == [
        "system-dotnet", "exec", "--roll-forward", "LatestPatch", str(headless_runtime.ENGINE),
    ]
