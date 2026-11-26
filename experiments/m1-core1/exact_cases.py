import gzip
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"hotdraw"))
from check import card,request
from build import checksum


def cases():
    hand = [card("FLASH_OF_STEEL"),card("STRIKE_IRONCLAD","Draw"),card("DEFEND_IRONCLAD","Draw")]
    strike = card("STRIKE_IRONCLAD")
    defend = card("DEFEND_IRONCLAD")
    yield "adapt","core1",request("adapt",hand,hp=9)
    yield "shuffle","core1-native",request("native",[strike,card("STRIKE_IRONCLAD","Draw",count=2),
        card("DEFEND_IRONCLAD","Draw"),card("BASH","Discard")])
    yield "menu","core1",request("menu",[card("BURNING_PACT"),strike,defend,card("BASH","Draw")])
    yield "order","core1",request("order",[strike,defend],energy=2)
    yield "death","core1",request("death",[strike]) | dict(initialPlayerHp=1)
    yield "budget","core1-cap",request("cap",hand)
    yield "unsupported","core1",request("unsupported",[card("HAVOC"),strike])


def run(identity,out):
    build = json.loads(identity.read_bytes())
    for name,sha in (("runtime","runtime_sha256"),("solver","solver_sha256"),("dll","harness_sha256")):
        assert checksum(Path(build[name]))==build[sha]
    out.mkdir(parents=True,exist_ok=False)
    begin = perf_counter()
    rows = {}
    for name,mode,spec in cases():
        folder = out/name
        folder.mkdir()
        req,res = folder/"request.json",folder/"result.json"
        req.write_text(json.dumps(spec))
        with (folder/"host.log").open("wb") as f:
            rc = subprocess.run([build["runtime"],build["dll"],"--hotdraw",mode,str(req.resolve()),str(res.resolve())],
                    cwd=identity.parent/("CombatSolver-"+build["upstream"]),stdout=f,stderr=subprocess.STDOUT,timeout=120)
        rows[name] = json.loads(res.read_bytes()) if rc.returncode==0 else {"error":rc.returncode}
        print(name,rc.returncode,flush=True)
    data=dict(rows=rows,seconds=perf_counter()-begin,build={k:v for k,v in build.items() if k not in ("runtime","solver","dll")})
    (out/"exact.json.gz").write_bytes(gzip.compress(json.dumps(data,separators=(",",":")).encode(),mtime=0))
    return any("error" in r for r in rows.values())


if __name__=="__main__":
    raise SystemExit(run(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()))
