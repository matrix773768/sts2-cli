"""Mirror Calcify through the native card and powered-damage paths."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III4 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii4/build_solver.py"))
IIH = III4["IIH"]


def lifecycle(source):
    III4["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<Outrage>(BespokeCardMirrors.OutrageOnPlay);",
         """        registry.Register<Outrage>(BespokeCardMirrors.OutrageOnPlay);
        registry.Register<Calcify>(BespokeCardMirrors.CalcifyOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)",
         """    public static void CalcifyOnPlay(Calcify card, CardOnPlayMirrorContext context)
    {
        if (context.Simulator.IsOverOrEnding)
            return;
        if (context.State.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Calcify requires a writable prediction state.");
        effects.ApplyPowerFromSource(typeof(CalcifyPower), card.Owner.Creature,
            card.DynamicVars["CalcifyPower"].IntValue, card.Owner.Creature, card);
    }

    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)""")
    edit(source / "Prediction/CardOnPlayCompensationCatalog.cs",
         "typeof(Calamity), typeof(Calcify), typeof(CallOfTheVoid)",
         "typeof(Calamity), typeof(CallOfTheVoid)")
    edit(source / "Prediction/CardPowerOnPlaySupport.cs",
         """            case Calcify:
                combat.Apply<CalcifyPower>(owner, card.DynamicVars["CalcifyPower"].IntValue, owner);
                break;
""", "")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iii.5", subprocess=SimpleNamespace(run=stage)))()
