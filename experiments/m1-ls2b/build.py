"""Build the opt-in StrategySpec command in a separate LS2A research host."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
base = runpy.run_path(str(HERE.parent / "m1-ls2a/build.py"))


def stage(src):
    base["stage"](src)
    shutil.copyfile(HERE / "Strategy.cs", src / "ComposedStrategy.cs")
    base["edit"](src / "Host.cs", ': request.TryGetProperty("ls2_trajectory"',
                 ': request.TryGetProperty("strategy_spec", out var spec) && arm == "C"'
                 '\n                    ? search.RunSpec(spec) : request.TryGetProperty("ls2_trajectory"')


if __name__ == "__main__":
    base["base"]["i1"].build(HERE.parents[1] / "logs/m1-ls2b-build", stage)
