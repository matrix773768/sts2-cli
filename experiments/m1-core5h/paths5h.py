import json
from pathlib import Path

H=Path(__file__).resolve().parent
ROOT=H.parents[1]
INFRA=ROOT.parent/"sts2-infra"
G=H.parent/"m1-core5g"
E=H/"evidence"
W=ROOT/"logs/core5h"
E.mkdir(exist_ok=True)
W.mkdir(parents=True,exist_ok=True)
LONG=G/"evidence/long-4096-5719.pt"
SCRATCH=G/"evidence/scratch-4096-5719.pt"
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False),encoding="utf8")
