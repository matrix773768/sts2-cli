"""Hash the published artifacts, external rule inputs, implementation and training runtime."""
from pathlib import Path
import hashlib
import json
import platform
import sys
import torch
import numpy

def sha(path):
    data=path.read_bytes()
    if path.suffix in (".json",".py"):data=data.replace(b"\r\n",b"\n")
    return hashlib.sha256(data).hexdigest()

def write(out):
    here=Path(__file__).resolve().parent
    files=[here/"cards.json.gz",here.parent/"m1-core2/catalog.json.gz",here.parent/"m1-core3/evidence/simple.pt",
           *sorted((here.parent/"m1-core3/evidence").glob("fights*.gz"))]
    meta=dict(start_commit="065e5af94b493b12b1a8bad65b15fcb3fc400b0c",text_hash="LF-normalized UTF-8",
              G2_sha256=json.loads((here.parent/"m1-core3/evidence/manifest.json").read_text())["G2_sha256"],
              runtime=dict(python=platform.python_version(),numpy=numpy.__version__,torch=torch.__version__),
              rule_and_history_sha256={p.relative_to(here.parent).as_posix():sha(p) for p in files},
              implementation_sha256={p.name:sha(p) for p in here.glob("*.py")},
              artifact_sha256={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!="manifest.json"})
    (out/"manifest.json").write_text(json.dumps(meta,indent=2)+"\n")
if __name__=="__main__":write(Path(sys.argv[1]))
