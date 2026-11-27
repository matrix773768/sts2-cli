"""Stage immutable runtime inputs into a disposable INFRA checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "5bb7c68bbb66e25b419460743d09f74568ca3372"
BIN = "Headless/bin/Debug/net9.0"
E = ROOT / "experiments/m1-infra0/evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_paths():
    paths = ["lib", "logs/m0-v5/dotnet9", "logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt",
             "logs/iik3b-solver/bin", "logs/iik3b-solver/build.json"]
    for host in ("iik4b-host-final", "m1-pre0b-host-final", "n4b-host-v2", "core5a-host3", "core5b-host", "core5c-host"):
        prefix = "logs/" + host + "/"
        paths += [prefix + "build.json", prefix + ("" if host in ("iik4b-host-final","m1-pre0b-host-final") else "host/") + BIN]
        if host not in ("iik4b-host-final","m1-pre0b-host-final"):
            paths.append(prefix + "solver-bin")
    paths.append("logs/iik5-main-host/bin/Debug/net9.0")
    return paths


def prepare(source):
    branch = subprocess.check_output(["git", "-C", ROOT, "branch", "--show-current"], text=True).strip()
    if branch != "research/m1-infra" or source.resolve() == ROOT:
        raise ValueError("Use the independent INFRA checkout")
    subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    paths = runtime_paths()
    for name in paths:
        src = source / name
        for item in src.rglob("*") if src.is_dir() else [src]:
            if item.is_dir():
                continue
            dest = ROOT / item.relative_to(source)
            if dest.resolve() != dest:
                raise ValueError(f"Redirected destination {dest}")
            if dest.exists():
                if sha(dest) != sha(item):
                    raise ValueError(f"Existing dependency differs: {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, dest)

    ledger = json.loads((ROOT/"experiments/m1-core5c/evidence/ledger.json").read_bytes())
    expected = {"logs/core5c-host/" + k:v for k,v in ledger["host"].items()}
    expected.update({"lib/sts2.dll":ledger["game"],paths[2]:ledger["g2"],
                     "experiments/m1-core5a/evidence/v2.pt":ledger["weights"]["v2"]})
    expected.update({"experiments/"+k:v for k,v in ledger["static_rules"].items()})
    for name, value in expected.items():
        if sha(ROOT/name) != value:
            raise ValueError(f"Frozen identity mismatch: {name}")
    verify_inputs()
    print(json.dumps(expected, indent=2))


def verify_inputs():
    manifest=json.loads((E/"inputs.json").read_bytes())
    for name,value in manifest["files"].items():
        if sha(ROOT/name)!=value:raise ValueError(f"Dependency changed: {name}")
    for name,value in manifest["shared"].items():
        if sha(Path(name))!=value:raise ValueError(f"Shared dependency changed: {name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source.resolve())
