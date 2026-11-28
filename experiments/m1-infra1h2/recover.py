"""Locate byte-identical frozen Workshop binaries in official release assets."""
import hashlib
import json
from pathlib import Path
import struct
from urllib.request import Request,urlopen
import zipfile
import zlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/"logs/infra1h2"
API="https://api.github.com/repos/BAKAOLC/STS2-RitsuLib/releases"
def fetch(url,accept):
    return urlopen(Request(url,headers={"Accept":accept,"User-Agent":"sts2-infra-h2"}),timeout=55)
def run():
    identity=json.loads((ROOT/"experiments/m1-infra0/evidence/inputs.json").read_bytes())["shared"]
    original=next(Path(k).parent for k in identity if k.endswith("3747602295\\STS2-RitsuLib.dll"))
    expected={Path(k).relative_to(original).as_posix():v for k,v in identity.items() if Path(k).is_relative_to(original)}
    with fetch(API+"?per_page=25","application/vnd.github+json") as response:
        versions=json.load(response)
    for release in versions:
        if not release["tag_name"].startswith("v0.6."):continue
        asset=next((a for a in release["assets"] if a["name"].endswith("variant-pack.zip")),None)
        if not asset:continue
        with fetch(asset["url"],"application/octet-stream") as response:
            prefix=response.read(256*1024);start=0;found=False
            while prefix[start:start+4]==b"PK\x03\x04":
                header=struct.unpack_from("<I5H3I2H",prefix,start);size=header[7]
                pos=start+30;name=prefix[pos:pos+header[-2]].decode()
                pos+=header[-2]+header[-1];end=pos+size
                if end>len(prefix):break
                if name=="STS2-RitsuLib.dll":
                    digest=hashlib.sha256(zlib.decompress(prefix[pos:end],-15)).hexdigest()
                    found=digest==expected[name]
                    print(release["tag_name"],digest,found,flush=True);break
                start=end
            if not found:continue
            archive=OUT/"frozen-ritsu.zip"
            with archive.open("wb") as f:
                f.write(prefix)
                while chunk:=response.read(1024*1024):f.write(chunk)
        if "sha256:"+hashlib.sha256(archive.read_bytes()).hexdigest()!=asset["digest"]:raise ValueError("asset digest")
        dest=OUT/"frozen-ritsu"
        with zipfile.ZipFile(archive) as z:
            for name,digest in expected.items():
                data=z.read(name)
                if hashlib.sha256(data).hexdigest()!=digest:raise ValueError(name)
                p=dest/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        (dest/"origin.json").write_text(json.dumps(dict(tag=release["tag_name"],asset=asset["url"],digest=asset["digest"],
                                                        files=expected),indent=2))
        return
    raise RuntimeError("No byte-identical release found")
if __name__=="__main__":run()
