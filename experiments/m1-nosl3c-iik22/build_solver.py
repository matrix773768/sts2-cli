"""Build II-K.2.2 with Lightning Rod's native ending guard."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIK21 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iik21/build_solver.py"))
IIH = IIK21["IIH"]


def lifecycle(source):
    IIK21["lifecycle"](source)
    IIH["edit"](
        source / "Engine/InCombat/Mirrors/Hooks/Resources/AfterEnergyResetMirrors.cs",
        "        context.Combat.SetAmount<LightningRodPower>(context.Player.Creature, power.Amount - 1);",
        """        // Native PowerCmd.Decrement skips amount changes if the channel's evoke ended combat.
        if (!context.Simulator.IsEnding)
            context.Combat.SetAmount<LightningRodPower>(context.Player.Creature, power.Amount - 1);""",
    )


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.2.2", subprocess=SimpleNamespace(run=stage)))()
