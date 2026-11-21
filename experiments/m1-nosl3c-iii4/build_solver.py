"""Complete Outrage on top of the II-I.3 Solver."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III3 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii3/build_solver.py"))
IIH = III3["IIH"]


def lifecycle(source):
    III3["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<Underworld>(BespokeCardMirrors.UnderworldOnPlay);",
         """        registry.Register<Underworld>(BespokeCardMirrors.UnderworldOnPlay);
        registry.Register<Outrage>(BespokeCardMirrors.OutrageOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)",
         """    public static void OutrageOnPlay(Outrage card, CardOnPlayMirrorContext context)
    {
        DamageCmd.Attack(card.DynamicVars.Damage.BaseValue)
            .FromCard(card, context.CardPlay)
            .Targeting(context.Target)
            .Simulate(context.Simulator);
        if (context.Simulator.HasPendingChoice)
        {
            context.Simulator.RejectExecutionContinuation();
            return;
        }

        // Native GetTeammatesOf includes the owner. Only living player
        // creatures receive a clone, and generated cards use the source owner as creator.
        foreach (Creature teammate in context.State.GetTeammatesOf(card.Owner.Creature))
        {
            if (teammate.Player is not { } player || !context.State.GetCreature(teammate).IsAlive)
                continue;
            context.Simulator.AddGeneratedCardToCombat(
                context.Card.CreateCloneForPlayer(player), PileType.Discard, card.Owner,
                CardPilePosition.Bottom, CardGenerationResultKind.Fixed);
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
        VERSION="0.51.5-iii.4", subprocess=SimpleNamespace(run=stage)))()
