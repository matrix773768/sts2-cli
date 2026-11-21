"""Mirror Legion of Bone through the shared Osty summon path."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III5 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii5/build_solver.py"))
IIH = III5["IIH"]


def lifecycle(source):
    III5["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<Calcify>(BespokeCardMirrors.CalcifyOnPlay);",
         """        registry.Register<Calcify>(BespokeCardMirrors.CalcifyOnPlay);
        registry.Register<LegionOfBone>(BespokeCardMirrors.LegionOfBoneOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)",
         """    public static void LegionOfBoneOnPlay(LegionOfBone card, CardOnPlayMirrorContext context)
    {
        if (context.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Legion of Bone requires a writable prediction state.");

        int amount = card.DynamicVars.Summon.IntValue;
        foreach (Creature recipient in context.CombatState.PlayerCreatures
                     .Where(creature => context.State.GetCreature(creature).IsAlive).ToArray())
        {
            effects.SummonOsty(context.Simulator, recipient.Player!, amount);
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
        VERSION="0.51.5-iii.6", subprocess=SimpleNamespace(run=stage)))()
