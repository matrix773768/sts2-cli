"""Build the N2A.3 harness on the frozen HotDraw structure overlay."""
import argparse
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "structures"))
from build_structures import extend
from build import build, checksum, edit


def wire(tree, harness):
    identity = extend(tree, harness)
    edit(harness / "HotDrawHarness.cs", "            : RunFixture(fixture, request, root, loop, combat);",
         '''            : fixture == "reachability"
                ? RunReachability(requestPath, request, root)
                : RunFixture(fixture, request, root, loop, combat);''')
    for path in HERE.glob("*.cs"):
        shutil.copyfile(path, harness / path.name)
    return identity | {"reachability": {p.name: checksum(p) for p in sorted(HERE.iterdir())
                                         if p.suffix in {".cs", ".py"} or p.name == "fixtures.json"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.archive.resolve(), args.steam.resolve(), extension=wire)
