"""Install open condition workloads from the immutable Git object database."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from infra_assets import BIN,ROOT,sha

REV="70e2e28b2915b962e93e3b30d3ec41aa5875fc6f"
HERE=Path(__file__).resolve().parent
OPEN=ROOT/"logs/infra0-world-inputs"
CODE=ROOT/"experiments/m1-core5e"
def blob(path):
    return subprocess.check_output(["git","show",f"{REV}:{path}"],cwd=ROOT)

def setup(source):
    OPEN.mkdir(parents=True,exist_ok=True)
    CODE.mkdir(exist_ok=True)
    imported={}
    for name in ["conditions5e.py","panel5e.py","data5e.py","targets5e.py"]+[
        f"evidence/{prefix}-{i}.gz" for prefix,n in (("worlds-train",4),("worlds-dev",2),("audit12-train",2)) for i in range(n)]:
        raw=blob("experiments/m1-core5e/"+name)
        dest=(CODE/name if "/" not in name else OPEN/Path(name).name)
        if not dest.exists():dest.write_bytes(raw)
        current=dest.read_bytes()
        if name.endswith(".py"):
            current=current.replace(b"\r\n",b"\n")
            original=raw.replace(b"\r\n",b"\n")
        else:
            original=raw
        if current!=original:
            measured="02ceab2646dc3e1247f8dbe2f7843d056dec81b78267e4336116ae8ce8706301"
            if name!="conditions5e.py" or hashlib.sha256(current).hexdigest()!=measured:
                raise ValueError(f"Unexpected change to {dest}")
        imported[name]=hashlib.sha256(raw).hexdigest()
    ledger=json.loads(blob("experiments/m1-core5e/evidence/ledger.json"))
    frozen=ROOT/"logs/core5e-world-host"
    shared=source/"logs/core5e-world-host"
    if not frozen.exists():
        frozen.mkdir()
        for path in ["build.json","solver-bin","host/"+BIN]:
            if (shared/path).is_file():shutil.copyfile(shared/path,frozen/path)
            else:shutil.copytree(shared/path,frozen/path)
    identity=ledger["world_host"]
    for path,value in identity["artifacts"].items():
        if sha(frozen/path)!=value:raise ValueError(path)
    if sha(ROOT/"lib/sts2.dll")!=identity["game"]:raise ValueError("game")
    if sha(ROOT/"experiments/m1-core5a/evidence/v2.pt")!=ledger["weights"]["v2"]:raise ValueError("V2")
    for path,value in ledger["static"].items():
        if sha(ROOT/"experiments"/path)!=value:raise ValueError(path)
    # Build the open split view from the original source/index joins. Each archived
    # case carries its original 5E index, family, 5D source index and opening seed.
    source5d=ROOT/"experiments/m1-core5d/evidence"
    groups={}
    for fname,keys in (("panel.gz",("train","dev")),("augmentation.gz",("dev2",))):
        value=json.load(gzip.open(source5d/fname))
        groups.update({k:value[k] for k in keys})
    panel={}
    for split,count in (("train",128),("dev",48)):
        w={}
        for path in OPEN.glob(f"worlds-{split}-*.gz"):
            for r in map(json.loads,gzip.open(path)):
                root=groups[r["source"]][r["index"]]
                if (root["family"],root["spec"]["seed"])!=(r["family"],r["seed"]):raise ValueError("bad join")
                w[r["i"]]=root|dict(source=r["source"],index=r["index"])
        panel[split]=[w[i] for i in range(count)]
    (OPEN/"panel.gz").write_bytes(gzip.compress(json.dumps(panel,separators=(",",":")).encode(),mtime=0))
    manifest=dict(commit=REV,world_host=identity,imports=imported,open_panel=sha(OPEN/"panel.gz"),
        frozen_source_sha256={name:hashlib.sha256(blob("experiments/m1-core5e/"+name)).hexdigest()
            for name in ("conditions5e.py","panel5e.py","data5e.py","targets5e.py","host5e.py")})
    (OPEN/"inputs.json").write_text(json.dumps(manifest,indent=2))
if __name__=="__main__":
    import sys
    setup(Path(sys.argv[1]).resolve())
