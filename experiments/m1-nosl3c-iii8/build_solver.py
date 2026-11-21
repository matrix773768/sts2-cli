"""Mirror Plot's same-side delayed draw using the shared power path."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III7 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii7/build_solver.py"))
IIH = III7["IIH"]


def lifecycle(source):
    III7["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<GlimpseBeyond>(BespokeCardMirrors.GlimpseBeyondOnPlay);",
         """        registry.Register<GlimpseBeyond>(BespokeCardMirrors.GlimpseBeyondOnPlay);
        registry.Register<Plot>(BespokeCardMirrors.PlotOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)",
         """    public static void PlotOnPlay(Plot card, CardOnPlayMirrorContext context)
    {
        if (context.Simulator.IsOverOrEnding)
            return;
        if (context.State.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Plot requires a writable prediction state.");

        Creature owner = card.Owner.Creature;
        foreach (Creature teammate in context.State.GetTeammatesOf(owner))
        {
            if (teammate?.Player is null || !context.State.GetCreature(teammate).IsAlive)
                continue;

            effects.ApplyPowerFromSource(typeof(DrawCardsNextTurnPower), teammate,
                card.DynamicVars.Cards.IntValue, owner, card);
            if (context.Simulator.HasPendingChoice)
            {
                context.Simulator.RejectExecutionContinuation();
                return;
            }
        }
    }

    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iii.8", subprocess=SimpleNamespace(run=stage)))()
