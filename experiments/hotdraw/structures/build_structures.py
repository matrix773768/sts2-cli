"""Build N2A.2 into an isolated HotDraw overlay."""
import argparse
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import build, checksum, edit


def extend(tree, harness):
    edit(tree / "src/HotKernel/Session.cs", '"BURNING_BLOOD", "THE_ABACUS"',
         '"BURNING_BLOOD", "THE_ABACUS", "LETTER_OPENER"')
    edit(harness / "HotDrawHarness.cs", "        object result = RunFixture(fixture, request, root, loop, combat);",
         '''        object result = fixture == "structures"
            ? RunStructures(requestPath, request, root, loop, combat)
            : RunFixture(fixture, request, root, loop, combat);''')
    for path in HERE.glob("*.cs"):
        shutil.copyfile(path, harness / path.name)
    return {"structures": {path.name: checksum(path) for path in sorted(HERE.iterdir())
                            if path.suffix in {".cs", ".py"} or path.name == "fixtures.json"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.archive.resolve(), args.steam.resolve(), extension=extend)
