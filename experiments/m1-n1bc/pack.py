"""Package the immutable pilot inputs, models and measured runs from this machine."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

HERE=Path(__file__).resolve().parent
LOGS=HERE.parents[1]/"logs"


def write_zip(path, paths):
    with ZipFile(path,"x",ZIP_DEFLATED,compresslevel=3) as archive:
        for p in sorted(set(paths)):
            archive.write(p,p.relative_to(LOGS).as_posix())
    with ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("Pilot artifact CRC mismatch")


def pack(out):
    out.mkdir(parents=True,exist_ok=False)
    raw=[]
    models=[]
    timings={}
    for d in sorted(LOGS.glob("n1bc-*")):
        if not d.is_dir():
            continue
        if (d/"model.pt").is_file():
            models += [d/"model.pt"]
            raw += [d/"samples.json", d/"result.json"]
            fit=json.loads((d/"result.json").read_bytes())
            timings[d.name]=fit["prepare_s"]+fit["seconds"]
        if (d/"run.json").is_file():
            raw += [d/"run.json",d/"manifest.json",*d.glob("*.json.gz")]
            timings[d.name]=json.loads((d/"run.json").read_bytes())["seconds"]
        if (d/"audit.json").is_file():
            raw.append(d/"audit.json")
            timings[d.name]=json.loads((d/"audit.json").read_bytes())["seconds"]
    catalog=LOGS/"n1bc-catalog"
    raw += [*catalog.glob("*/request.json"),*catalog.glob("*/export.json"),LOGS/"n1bc-host/build.json"]
    rank=LOGS/"n1bc-ranking"
    raw += [*rank.glob("*.json.gz"),rank/"ranking.json"]
    timings[rank.name]=json.loads((rank/"ranking.json").read_bytes())["seconds"]
    with gzip.open(catalog/"catalog.json.gz") as f:
        timings[catalog.name]=json.load(f)["seconds"]
    for name,files in (("raw.zip",raw),("models.zip",models)):
        write_zip(out/name,files)
    report={k:json.loads((LOGS/f"n1bc-{k}.json").read_bytes()) for k in
            ("qualified","summary","ablation","cost")}
    report["timing_seconds"]=timings
    report["measured_seconds_sum"]=sum(timings.values())
    report["native"]={p.parent.name:json.loads(p.read_bytes()) for p in raw if p.name=="audit.json"}
    report["models"]={p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    report["archives"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob("*.zip")}
    (out/"results.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")


if __name__=="__main__":
    pack(Path(sys.argv[1]))
