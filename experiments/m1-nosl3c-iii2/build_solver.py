"""Build the Hibernate mirror on top of II-I.1."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III1 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii1/build_solver.py"))
IIH = III1["IIH"]


def lifecycle(source):
    III1["lifecycle"](source)
    edit = IIH["edit"]
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<HammerTime>(BespokeCardMirrors.HammerTimeOnPlay);",
         """        registry.Register<HammerTime>(BespokeCardMirrors.HammerTimeOnPlay);
        registry.Register<Hibernate>(OrbCardMirrors.HibernateOnPlay);""")
    edit(cards / "OrbCardMirrors.cs",
         "    public static void ConsumingShadowOnPlay(ConsumingShadow card, CardOnPlayMirrorContext context)",
         """    public static void HibernateOnPlay(Hibernate card, CardOnPlayMirrorContext context)
    {
        if (context.Simulator.IsOverOrEnding)
            return;
        if (context.State.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("Hibernate requires a writable prediction state.");

        effects.ApplyPowerFromSource(typeof(HibernatePower), card.Owner.Creature, 1,
            card.Owner.Creature, context.CardPlay.Card);
        context.Simulator.OrbChannel<FrostOrb>(card.Owner, card.DynamicVars.Repeat.IntValue);
    }

    public static void ConsumingShadowOnPlay(ConsumingShadow card, CardOnPlayMirrorContext context)""")
    edit(source / "Engine/InCombat/Mirrors/Orbs/FrostOrbMirrors.cs",
         "        if (!orb.Owner.Creature.HasPower<HibernatePower>())",
         """        bool hasHibernate = context.State.CombatState is SimulatedCombatState combat
            ? combat.GetAmount<HibernatePower>(orb.Owner.Creature) > 0
            : orb.Owner.Creature.HasPower<HibernatePower>();
        if (!hasHibernate)""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iii.2", subprocess=SimpleNamespace(run=stage)))()
