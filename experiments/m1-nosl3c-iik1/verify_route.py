"""Replay the first 51 frozen decisions of pair16 root 0:000009."""
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import probe

if __name__ == "__main__":
    output, solver = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    tools["targets"].configure()
    versions = tools["bind"](output, solver)
    batch = tools["batch"]("iij5b-serial-pair16", 0, "000009")
    batch["rows"][0]["transitions"] = batch["rows"][0]["transitions"][:51]
    result = probe(output, versions, batch, False, False)
    tools["save_json"](output / "route.json", dict(engine=versions, result=result))
    print(result["status"], result.get("position"), result.get("differences"))
