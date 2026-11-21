"""Build the II-H.6 candidate with native Illusion death-hook scope."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH5 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih5/build_solver.py"))
IIH = IIH5["IIH"]
VERSION = "0.51.5-iih.6.1"


def lifecycle(source):
    IIH5["lifecycle"](source)
    IIH["edit"](source / "Search/SimulatedCombatState.DeathLifecycle.cs",
                """        bool hasIllusionHook = EffectivePowers().Any(power =>
            power is IllusionPower
            && power.Amount > 0
            && ReferenceEquals(power.Owner, creature));""",
                """        // Native death cleanup polls all combat listeners while the dying
        // creature is attached. Illusion's veto is independent of power owner.
        IllusionPower? illusion = ContainsCreature(creature)
            ? IterateHookListeners().OfType<IllusionPower>().FirstOrDefault()
            : null;""")
    IIH["edit"](source / "Search/SimulatedCombatState.DeathLifecycle.cs",
                """            bool keep = !power.ShouldPowerBeRemovedAfterOwnerDeath();
            if (hasIllusionHook)
            {
                keep = power.Type != PowerType.Debuff || power is ITemporaryPower;
            }
            if (!keep)""",
                """            if (power.ShouldPowerBeRemovedAfterOwnerDeath()
                && (illusion == null || illusion.ShouldPowerBeRemovedOnDeath(power)))""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    patched = FunctionType(upstream.__code__, upstream.__globals__ |
                           {"duration_lifecycle": lifecycle})
    patched(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ |
                 dict(VERSION=VERSION, subprocess=SimpleNamespace(run=stage)))()
