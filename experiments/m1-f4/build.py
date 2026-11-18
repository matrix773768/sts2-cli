"""Build F4 alongside the unmodified F3B C path."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f4_f3db", HERE.parent / "m1-f3d-b/build.py")
f3db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3db)


def stage(src):
    f3db.stage(src)
    edit = f3db.f3da.s2a.s1.f3b.f3a.f2.replace
    shutil.copyfile(HERE / "QualitySearch.cs", src / "QualitySearch.cs")
    probe = src / "IntegrationProbe.cs"
    edit(probe, '            case "i1_f3b":', '            case "i1_f4":\n            case "i1_f3b":')
    edit(probe, 'if (command == "i1_f3b")', 'if (command is "i1_f3b" or "i1_f4")')
    edit(src / "Host.cs",
         '["search"] = search.Run(arm, request.TryGetProperty("repair_probe", out var probe) ? probe : null)',
         '''["search"] = request.GetProperty("cmd").GetString() == "i1_f4"
                ? search.RunQuality(request)
                : search.Run(arm, request.TryGetProperty("repair_probe", out var probe) ? probe : null)''')


if __name__ == "__main__":
    i1 = f3db.f3da.s2a.s1.f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs/m1-f4-build", stage)
