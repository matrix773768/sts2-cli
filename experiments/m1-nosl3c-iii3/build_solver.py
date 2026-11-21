"""Build the Underworld mirror on top of II-I.2."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III2 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii2/build_solver.py"))
IIH = III2["IIH"]


def lifecycle(source):
    III2["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<Hibernate>(OrbCardMirrors.HibernateOnPlay);",
         """        registry.Register<Hibernate>(OrbCardMirrors.HibernateOnPlay);
        registry.Register<Underworld>(BespokeCardMirrors.UnderworldOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs",
         "    public static void HammerTimeOnPlay(HammerTime card, CardOnPlayMirrorContext context)",
         """    public static void UnderworldOnPlay(Underworld card, CardOnPlayMirrorContext context)
    {
        if (context.Simulator.IsOverOrEnding)
            return;
        if (context.State.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Underworld requires a writable prediction state.");
        effects.ApplyPowerFromSource(typeof(UnderworldPower), card.Owner.Creature, 1, card.Owner.Creature, card);
    }

    public static void HammerTimeOnPlay(HammerTime card, CardOnPlayMirrorContext context)""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iii.3", subprocess=SimpleNamespace(run=stage)))()
