"""Build the II-I.1 Hammer Time mirror over the accepted Solver."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH8 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih8/build_solver.py"))
IIH = IIH8["IIH"]


def lifecycle(source):
    IIH8["lifecycle"](source)
    edit = IIH["edit"]
    mirrors = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(mirrors / "CardOnPlayMirrors.cs",
         "        registry.Register<SovereignBlade>(BespokeCardMirrors.SovereignBladeOnPlay);",
         """        registry.Register<SovereignBlade>(BespokeCardMirrors.SovereignBladeOnPlay);
        registry.Register<HammerTime>(BespokeCardMirrors.HammerTimeOnPlay);""")
    edit(mirrors / "BespokeCardMirrors.cs",
         "    public static void ExpectAFightOnPlay(ExpectAFight card, CardOnPlayMirrorContext context)",
         """    public static void HammerTimeOnPlay(HammerTime card, CardOnPlayMirrorContext context)
    {
        if (context.Simulator.IsOverOrEnding)
            return;
        if (context.State.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Hammer Time requires a writable prediction state.");
        effects.ApplyPowerFromSource(typeof(HammerTimePower), card.Owner.Creature, 1, card.Owner.Creature, card);
    }

    public static void ExpectAFightOnPlay(ExpectAFight card, CardOnPlayMirrorContext context)""")
    forge = source / "Prediction/PersistentPowerSupport.cs"
    edit(forge, """        int amount)
    {
        if (simulator.HasPendingChoice)
            return;

        SimPlayerCombatState state""", """        int amount)
        => Forge(simulator, player, amount, copiedByHammerTime: false);

    private static void Forge(
        CombatPredictionSimulator simulator,
        Player player,
        int amount,
        bool copiedByHammerTime)
    {
        if (simulator.HasPendingChoice || simulator.IsOverOrEnding)
            return;

        SimPlayerCombatState state""")
    edit(forge, """            ((SovereignBlade)card.MutablePreview).AddDamage(amount);
        }
    }""", """            ((SovereignBlade)card.MutablePreview).AddDamage(amount);
        }

        // Hammer Time listens after the original Blade instances have been updated.
        // A copied Forge does not trigger another copy, even with two owners.
        if (copiedByHammerTime
            || simulator.State.CombatState is not SimulatedCombatState combat
            || combat.GetAmount<HammerTimePower>(player.Creature) <= 0)
            return;

        foreach (Player ally in combat.Players)
        {
            if (ally == player || !simulator.State.GetCreature(ally.Creature).IsAlive)
                continue;
            Forge(simulator, ally, amount, copiedByHammerTime: true);
            if (simulator.HasPendingChoice)
                return;
        }
    }""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iii.1", subprocess=SimpleNamespace(run=stage)))()
