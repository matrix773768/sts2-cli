"""Build an isolated Solver with native ending semantics for mirrored orb effects."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih/build_solver.py"))
VERSION = "0.51.5-iih.4.1"


def duration_and_orb_power(source):
    IIH["duration_lifecycle"](source)
    death = source / "Prediction/DeathPowerSupport.cs"
    IIH["edit"](death, "        combat.RemovePowersAfterDeath(dead);",
                """        // Commit pending hook writes before death removes powers. A later sync
        // must not restore amounts carried by a stale damage-hook model.
        simulator.SynchronizePowerAmountPredictionStates();
        combat.RemovePowersAfterDeath(dead);""")
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay/OrbCardMirrors.cs"
    IIH["edit"](cards, '''        context.Simulator.OrbChannel<DarkOrb>(card.Owner, card.DynamicVars.Repeat.IntValue);
        if (context.Simulator.HasPendingChoice)
''', '''        context.Simulator.OrbChannel<DarkOrb>(card.Owner, card.DynamicVars.Repeat.IntValue);
        // PowerCmd.Apply rejects commands after an evocation ends combat.
        if (context.Simulator.HasPendingChoice || context.Simulator.IsOverOrEnding)
''')


def stage(command, **kwargs):
    upstream = IIH["stage"]
    patched = FunctionType(upstream.__code__, upstream.__globals__ |
                           {"duration_lifecycle": duration_and_orb_power})
    patched(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ |
                 dict(VERSION=VERSION, subprocess=SimpleNamespace(run=stage)))()
