"""Mirror Glimpse Beyond through the existing fixed card generation path."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III6 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii6/build_solver.py"))
IIH = III6["IIH"]


def lifecycle(source):
    III6["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<LegionOfBone>(BespokeCardMirrors.LegionOfBoneOnPlay);",
         """        registry.Register<LegionOfBone>(BespokeCardMirrors.LegionOfBoneOnPlay);
        registry.Register<GlimpseBeyond>(BespokeCardMirrors.GlimpseBeyondOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)",
         """    public static void GlimpseBeyondOnPlay(GlimpseBeyond card, CardOnPlayMirrorContext context)
    {
        foreach (Creature teammate in context.State.GetTeammatesOf(card.Owner.Creature))
        {
            if (teammate?.Player is not { } player || !context.State.GetCreature(teammate).IsAlive)
                continue;

            context.Simulator.CreateAndAddGeneratedCardsToCombat<Soul>(
                player, PileType.Draw, card.DynamicVars.Cards.IntValue, card.Owner,
                CardPilePosition.Random);
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
        VERSION="0.51.5-iii.7", subprocess=SimpleNamespace(run=stage)))()
