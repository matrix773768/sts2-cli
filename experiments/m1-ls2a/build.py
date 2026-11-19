"""Stage LS2A on the isolated LS1 host, leaving default search code unchanged."""
from pathlib import Path
import runpy
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-ls1"))
base = runpy.run_path(str(HERE.parent / "m1-ls1/build.py"))
edit = base["edit"]


def stage(src):
    base["stage"](src)
    for name in ("Catalog", "Trajectory"):
        shutil.copyfile(HERE / (name + ".cs"), src / ("Ls2" + name + ".cs"))
    program = src / "Program.cs"
    edit(program, "result = sim.SyntheticCatalog();", "result = sim.Ls2Catalog();")
    edit(program, 'or "set_draw_order" or "get_map"', 'or "set_draw_order"')
    combat = src / "SyntheticCombat.cs"
    edit(combat, 'spec.Act is not (1 or 2)', 'spec.Act < 1 || spec.Act > ModelDb.ActsByIndex.Count()')
    edit(combat, 'spec.ActVariant is null || spec.Character is not ("Ironclad" or "Silent")', 'spec.ActVariant is null')
    edit(combat, 'encounter.RoomType != RoomType.Monster || !acts[actIndex]', 'encounter.RoomType is not (RoomType.Monster or RoomType.Elite or RoomType.Boss) || !acts[actIndex]')
    edit(src / "Host.cs", ': search.Run(arm,', ': request.TryGetProperty("ls2_trajectory", out var trajectory) && arm == "C"\n'
         '                    ? search.RunTrajectory(trajectory.GetString()!) : search.Run(arm,')


if __name__ == "__main__":
    base["i1"].build(base["ROOT"] / "logs/m1-ls2a-build", stage)
