"""Stage the isolated M1-N1 command in a copy of the S3B host."""
from pathlib import Path
import runpy
import shutil
import sys

HERE = Path(__file__).resolve().parent
s3b = runpy.run_path(str(HERE.parent / "m1-s3b/build_host.py"))
s3a = s3b["s3a"]


def stage(src):
    s3b["stage"](src)
    install(src)


def stage_real(src):
    f3b = runpy.run_path(str(HERE.parent / "m1-f3b/build.py"))
    f3b["stage"](src)
    s3a.edit(src / "Host.cs", '["search"] = search.Run(arm,',
             '["search"] = false ? throw new InvalidOperationException() : search.Run(arm,')
    install(src)


def install(src):
    shutil.copyfile(HERE / "Initial.cs", src / "Initial.cs")
    s3a.edit(src / "Host.cs", ': search.Run(arm,',
             ': request.TryGetProperty("initial", out var initial) ? '
             'search.RunInitial(initial.GetString()!) : search.Run(arm,')
    s3a.edit(src / "RouteSearch.cs", "var attack = attacks.OrderByDescending",
             '''if (strategy is "THREAT_V1" or "DURABLE_V1")
        {
            chosenFocus = strategy == "THREAT_V1"
                ? view.Menu.Enemies.OrderByDescending(e => e.Incoming).ThenBy(e => e.Hp + e.Block).FirstOrDefault()?.Id
                : view.Menu.Enemies.OrderByDescending(e => e.Hp + e.Block).FirstOrDefault()?.Id;
            strategy = "ENGINE";
        }
        var attack = attacks.OrderByDescending''')


if __name__ == "__main__":
    i1 = s3a.b1b.b1a.i1
    if "--real-only" not in sys.argv:
        i1.build(i1.ROOT / "logs/m1-n1-build", stage)
    i1.build(i1.ROOT / "logs/m1-n1-real-build", stage_real)


