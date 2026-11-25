"""Build the independent public mechanism harness."""
import argparse
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reachability"))
from build_reachability import build, checksum, edit, wire


def extend(tree, harness):
    identity = wire(tree, harness)
    edit(harness / "HotDrawHarness.cs",
         "                : RunFixture(fixture, request, root, loop, combat);",
         """                : fixture == "mechanisms"
                    ? RunMechanisms(request, root)
                    : RunFixture(fixture, request, root, loop, combat);""")
    source = HERE / "MechanismHarness.cs"
    shutil.copyfile(source, harness / source.name)
    return identity | {"mechanisms": {source.name: checksum(source)}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.archive.resolve(), args.steam.resolve(), extension=extend)
