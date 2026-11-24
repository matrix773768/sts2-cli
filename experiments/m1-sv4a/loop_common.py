"""Shared contracts and frozen assets for the SV4A campaign."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SV3 = HERE.parent / "m1-sv3a"
sys.path.insert(0, str(SV3))
from sv_data import checksum, digest, write_json


def config():
    return json.loads((HERE / "config.json").read_bytes())


def sources(*names):
    return {name: checksum(HERE / name) for name in names}


def ancestor(cfg):
    import torch
    from sv_model import contract
    best_path, resume_path = (ROOT / cfg[key] for key in ("g0", "g0_resume"))
    best, resume = (torch.load(file, map_location="cpu", weights_only=True)
                    for file in (best_path, resume_path))
    catalog = json.loads((SV3 / "evidence.json").read_bytes())["local_sha256"]
    if any(checksum(file) != catalog[file.relative_to(ROOT).as_posix()] for file in (best_path, resume_path)):
        raise ValueError("G0 differs from the published SV3A evidence")
    if (best["epoch"] != resume["epoch"] or best["identity"] != resume["identity"]
            or best["sources"] != contract() or best["model"].keys() != resume["model"].keys()
            or not all(torch.equal(value, resume["model"][name]) for name, value in best["model"].items())):
        raise ValueError("G0 optimizer checkpoint does not belong to the selected weights")
    return dict(best=checksum(best_path), optimizer=checksum(resume_path), epoch=best["epoch"],
                parameters=len(best["model"]), optimizer_states=len(resume["optimizer"]["state"]),
                previous_updates=resume["updates"], policies=best["policies"])
