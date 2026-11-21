"""Build the candidate with native ending semantics for Pale Blue Dot's Power command."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIJ3 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij3/build_solver.py"))
IIH = IIJ3["IIH"]


def lifecycle(source):
    IIJ3["lifecycle"](source)
    IIH["edit"](source / "Prediction/PowerLifecycleSupport.cs",
        """            combat.SetPaleBlueDotActivated(power, true);
            combat.Apply<DrawCardsNextTurnPower>(owner, power.Amount, owner);""",
        """            combat.SetPaleBlueDotActivated(power, true);
            // Native PowerCmd.Apply refuses new applications once combat is ending.
            if (!simulator.IsEnding)
                combat.Apply<DrawCardsNextTurnPower>(owner, power.Amount, owner);""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iij.4", subprocess=SimpleNamespace(run=stage)))()
