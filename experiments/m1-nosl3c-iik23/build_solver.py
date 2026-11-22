"""Build II-K.2.3 with Glass Orb's ending-window passive behavior."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIK22 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iik22/build_solver.py"))
IIH = IIK22["IIH"]


def lifecycle(source):
    IIK22["lifecycle"](source)
    IIH["edit"](
        source / "Engine/InCombat/Simulation/CombatPredictionSimulator.Orb.cs",
        """        if (IsOverOrEnding || HasPendingChoice)
        {
            return;
        }

        OrbMirrors.InvokePassive(this, orb, target);""",
        """        // During the ending window, native Glass passives still decay even
        // when the preceding orb has left them with no targets.
        if (!IsInProgress || HasPendingChoice
            || (orb is not MegaCrit.Sts2.Core.Models.Orbs.GlassOrb && IsEnding))
        {
            return;
        }

        OrbMirrors.InvokePassive(this, orb, target);""",
    )


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.2.3", subprocess=SimpleNamespace(run=stage)))()
