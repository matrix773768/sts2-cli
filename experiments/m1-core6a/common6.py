"""Paths and pinned public interfaces for the CORE-only policy experiment."""
import json
import os
import tempfile
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1]
INFRA = CORE.parent / "sts2-infra"
A = INFRA / "experiments/m1-infra2a"
H5 = A.parent / "m1-infra1h5"
E = HERE / "evidence"
WORK = CORE / "logs/core6a"
E.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True, parents=True)
os.environ["HOTSEARCH_BUILD"] = str(INFRA / "logs/hotsearch-h5")
sys.path.insert(0, str(INFRA / "engine/HotSearch"))
from models import public_b, choice_b, Models, torch
from features import Encoder, powers, public_summary, variant, token
sys.path.insert(0,str(INFRA))
from engine.HotSearch.experience import digest, sha, read_rows

POLICY = "25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7"
BEHAVIOR = "51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616"
def read(path):
    return json.loads(path.read_bytes())
def save(path, obj):
    payload=json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False).encode()
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        stream.write(payload)
        temp=stream.name
    os.replace(temp,path)
