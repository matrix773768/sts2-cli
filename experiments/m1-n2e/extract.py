"""Extract canonical card metadata in an isolated headless build."""
import json
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = ROOT / "logs/m1-n2e-build"
IDS = {
    "Ironclad": "STRIKE_IRONCLAD DEFEND_IRONCLAD BASH INFLAME TWIN_STRIKE POMMEL_STRIKE SHRUG_IT_OFF FLAME_BARRIER IRON_WAVE",
    "Silent": "STRIKE_SILENT DEFEND_SILENT SURVIVOR BLADE_DANCE ACCURACY FOOTWORK DODGE_AND_ROLL BACKFLIP CLOAK_AND_DAGGER PREDATOR SLICE LEG_SWEEP SHIV",
}


def extract():
    base = runpy.run_path(str(ROOT / "experiments/m1-n2a1/build.py"))

    def stage(src):
        base["stage"](src)
        shutil.copyfile(HERE / "StaticCards.cs", src / "StaticCards.cs")
        base["s3a"].edit(src / "Program.cs", 'else if (kind == "synthetic_catalog")',
                         'else if (kind == "n2e_static_cards")\n'
                         '                    result = new() { ["cards"] = sim.StaticCards(cmd) };\n'
                         '                else if (kind == "synthetic_catalog")')

    base["s3a"].b1b.b1a.i1.build(BUILD, stage)
    host = os.environ.get("STS2_DOTNET", "dotnet")
    dll = BUILD / "Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    request = dict(cmd="n2e_static_cards", ids=[card for ids in IDS.values() for card in ids.split()])
    result = subprocess.run([host, str(dll)], cwd=ROOT, input=json.dumps(request) + "\n",
                            encoding="utf-8", stdout=subprocess.PIPE, check=True, timeout=60)
    wire, = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"cards":')]
    source = hashlib.sha256((ROOT / "lib/sts2.dll").read_bytes()).hexdigest()
    return {"game_dll_sha256": source, "cards": wire["cards"]}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(extract(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
