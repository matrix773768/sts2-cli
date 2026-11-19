"""Build the dependency probe without changing the frozen search dispatch."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p2_f4_build", HERE.parent / "m1-f4/build.py")
f4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f4)
i1 = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.f1.i1


def stage(src):
    f4.stage(src)
    shutil.copyfile(HERE / "PredictionBoundary.cs", src / "PredictionBoundary.cs")
    edit = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.replace
    anchor = '        string? command = cmd.GetProperty("cmd").GetString();'
    edit(src / "IntegrationProbe.cs", anchor, anchor + '''
        if (command is "i1_p2_export" or "i1_p2_import")
            return ProbePredictionBoundary(cmd, command);''')


if __name__ == "__main__":
    i1.build(i1.ROOT / "logs/m1-p2-build", stage)
