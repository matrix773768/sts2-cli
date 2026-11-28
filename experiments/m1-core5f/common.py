"""Locations and immutable release contracts for CORE-5F."""
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INFRA = Path(os.environ.get("CORE5F_INFRA", ROOT.parent / "sts2-infra")).resolve()
H5 = INFRA / "experiments/m1-infra1h5"
E = HERE / "evidence"
E.mkdir(exist_ok=True)
sys.path.insert(0, str(INFRA / "engine/HotSearch"))
sys.path.insert(0, str(HERE.parent / "m1-core5e"))
os.environ.setdefault("HOTSEARCH_BUILD", str(INFRA / "logs/hotsearch-h5"))
from panel5e import deck_for, digest, load, read
sys.path.insert(0, str(INFRA))
from engine.HotSearch.experience import scan, sha
from semantic import torch, expected, payoff

def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf8")

def utility(opening, end, maximum, death):
    return -50. if death else float(payoff(torch.tensor(opening-end), torch.tensor(maximum)))

def composition(spec):
    return digest(sorted(c["id"] for c in spec["deck"]))
