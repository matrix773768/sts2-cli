"""Build II-K.2.4 with the native ending guard on Suck's Strength application."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIK23 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iik23/build_solver.py"))
IIH = IIK23["IIH"]


def lifecycle(source):
    IIK23["lifecycle"](source)
    IIH["edit"](
        source / "Engine/InCombat/Mirrors/Hooks/Attack/AfterAttackMirrors.cs",
        """        if (triggeredHits > 0)
        {
            if (context.CombatState is not ICombatPredictionEffectSink effects)""",
        """        // Native PowerCmd.Apply rejects the Strength grant once combat is ending.
        if (triggeredHits > 0 && !context.Simulator.IsEnding)
        {
            if (context.CombatState is not ICombatPredictionEffectSink effects)""",
    )


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.2.4", subprocess=SimpleNamespace(run=stage)))()
