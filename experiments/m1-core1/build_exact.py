"""Isolated exact graph overlay, including N2A instance binding and strict replay."""
import argparse
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"hotdraw/structures"))
from build_structures import extend as structures
from build import build, checksum, edit


def extend(tree,harness):
    identity = structures(tree,harness)
    edit(harness/"HotDrawHarness.cs",'            : RunFixture(fixture, request, root, loop, combat);',
         '''            : fixture.StartsWith("core1")
                ? CoreTurn(fixture, request, root, loop, combat)
                : RunFixture(fixture, request, root, loop, combat);''')
    # N2A replay previously admitted only player card actions.
    edit(harness/"StructureTrace.cs","session.Actions(parent, false)","session.Actions(parent, true)")
    shutil.copyfile(HERE/"TurnGraph.cs",harness/"TurnGraph.cs")
    return identity | {"core1":checksum(HERE/"TurnGraph.cs")}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    parser.add_argument("archive",type=Path)
    parser.add_argument("steam",type=Path)
    a=parser.parse_args()
    build(a.output.resolve(),a.archive.resolve(),a.steam.resolve(),extension=extend)
