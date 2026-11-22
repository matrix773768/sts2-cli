"""Build II-K.1 on top of the accepted II-J.4 Solver."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIJ4 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij4/build_solver.py"))
IIH = IIJ4["IIH"]


def lifecycle(source):
    IIJ4["lifecycle"](source)
    IIH["edit"](source / "Search/SimulatedCombatState.cs",
                "if (ownerPlayer.Osty is { } osty)",
                "if (GetOsty(ownerPlayer) is { } osty)")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.1", subprocess=SimpleNamespace(run=stage)))()
