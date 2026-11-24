"""Frozen preregistration and SV4A assets."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SV4 = HERE.parent / "m1-sv4a"
sys.path.insert(0, str(SV4))

from loop_common import ROOT, checksum, digest, write_json

PRIOR = ROOT / "logs/m1-sv4a-formal"


def read(path):
    return json.loads(path.read_bytes())


def config():
    return read(HERE / "config.json")


def frozen(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f"Frozen file changed: {path}")
    else:
        write_json(path, value)


def arms():
    evidence = read(SV4 / "evidence.json")
    paths = {"D0": ROOT / read(SV4 / "config.json")["g0"],
             **{arm: PRIOR / "models" / arm / "best.pt" for arm in ("D2", "S2")}}
    paths |= {"D2-search": paths["D2"], "S0": paths["D0"]}
    result = {}
    for arm, path in paths.items():
        entry = evidence["arms"][arm]
        if checksum(path) != entry["weight"]:
            raise ValueError(f"Published checkpoint differs: {arm}")
        result[arm] = path, entry["condition"], entry["budget"]
    return result
