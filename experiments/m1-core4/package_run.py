"""Copy the measured outputs of a completed run into a new evidence directory."""
from pathlib import Path
from shutil import copyfile
import sys

def package(logs, out):
    from core4_roots import panels,gzip,json
    out.mkdir(parents=True,exist_ok=False)
    with gzip.open(out/"panels.json.gz","wt") as f:json.dump(panels(),f,separators=(",",":"))
    for source, prefix, count in (("nat","nat",6),("policy","on",6)):
        for i in range(count):
            copyfile(logs/f"c4-{source}{i}/rows.gz",out/f"{prefix}{i}.gz")
    copyfile(logs/"c4-val/rows.gz",out/"val.gz")
    for source, label in (("base","v0"),("update","v1")):
        for file, suffix in (("model.pt",".pt"),("fit.json","-fit.json")):
            copyfile(logs/f"c4-{source}"/file,out/(label+suffix))
    for f in sorted(logs.glob("c4-test-*/seconds.json")):
        copyfile(f.parent/"rows.gz",out/(f.parent.name[3:]+".gz"))

if __name__=="__main__":package(Path(sys.argv[1]),Path(sys.argv[2]))
