"""Build the four II-K.3B mirrors on the cumulative II-K.2.4 candidate."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIK24 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iik24/build_solver.py"))
IIH = IIK24["IIH"]
edit = IIH["edit"]


def lifecycle(source):
    IIK24["lifecycle"](source)
    cards = source / "Engine/InCombat/Mirrors/Cards/OnPlay"
    specs = source / "Prediction/CardEffectSpecRegistry.cs"
    damage = source / "Engine/InCombat/Mirrors/Hooks/Damage/ModifyDamageMirrors.cs"
    edit(specs, '        [typeof(SicEm)] = [Target<SicEmPower>("SicEmPower")],',
         '''        [typeof(SicEm)] = [Target<SicEmPower>("SicEmPower")],
        [typeof(Sneaky)] = [Owner<SneakyPower>("SneakyPower")],''')
    edit(specs, '        [typeof(TagTeam)] = [Target<TagTeamPower>(_ => 1)],',
         '''        [typeof(TagTeam)] = [Target<TagTeamPower>(_ => 1)],
        [typeof(Tank)] = [Owner<TankPower>(_ => 1)],''')
    edit(cards / "CardOnPlayMirrors.cs",
         "        registry.Register<Plot>(BespokeCardMirrors.PlotOnPlay);",
         """        registry.Register<Plot>(BespokeCardMirrors.PlotOnPlay);
        registry.Register<OneForAll>(BespokeCardMirrors.OneForAllOnPlay);
        registry.Register<BladeSymphony>(BespokeCardMirrors.BladeSymphonyOnPlay);""")
    edit(cards / "BespokeCardMirrors.cs", "    public static void PlotOnPlay",
         """    public static void OneForAllOnPlay(OneForAll card, CardOnPlayMirrorContext context)
    {
        if (context.CombatState is not ICombatPredictionEffectSink effects)
            throw new InvalidOperationException("One for All requires a writable prediction state.");

        foreach (var player in context.CombatState.Players)
        {
            if (context.Simulator.IsEnding)
                return;
            effects.ApplyPowerFromSource(typeof(OneForAllPower), player.Creature,
                card.DynamicVars["OneForAllPower"].IntValue, card.Owner.Creature, card);
        }
    }

    public static void BladeSymphonyOnPlay(BladeSymphony card, CardOnPlayMirrorContext context)
    {
        foreach (Creature teammate in context.State.GetTeammatesOf(card.Owner.Creature))
        {
            if (teammate.Player is not { } player || !context.State.GetCreature(teammate).IsAlive)
                continue;
            context.Simulator.CreateAndAddGeneratedCardsToCombat<Shiv>(
                player, PileType.Hand, card.DynamicVars.Cards.IntValue, creator: null);
            if (context.Simulator.HasPendingChoice)
            {
                context.Simulator.RejectExecutionContinuation();
                return;
            }
        }
    }

    public static void PlotOnPlay""")
    edit(damage, "        registry.Register<AimPower>(AimPowerMirrors.ModifyDamageAdditive);",
         """        registry.Register<AimPower>(AimPowerMirrors.ModifyDamageAdditive);
        registry.Register<OneForAllPower>(HandleOneForAllPower);""")
    edit(damage, "        registry.Register<QuietusPower>(QuietusPowerMirrors.ModifyDamageMultiplicative);",
         """        registry.Register<QuietusPower>(QuietusPowerMirrors.ModifyDamageMultiplicative);
        registry.Register<TankPower>((power, context) => context.Target == power.Owner
            && context.Props.IsPoweredAttack() ? power.DynamicVars["DamageIncrease"].BaseValue : 1m);
        registry.Register<GuardedPower>((power, context) => context.Target == power.Owner
            && context.Props.IsPoweredAttack() ? power.DynamicVars["DamageDecrease"].BaseValue : 1m);""")
    edit(damage, "    private static decimal HandleFlutterPower",
         """    private static decimal HandleOneForAllPower(OneForAllPower power, ModifyDamageMirrorContext context)
    {
        if (!context.Props.IsPoweredAttack() || context.CardSource is not { } card
            || card.Preview.Owner.Creature != power.Owner)
            return 0m;

        CardPlay? play = context.CardPlay;
        if ((play?.Card ?? card.Preview).EnergyCost.CostsX)
            return 0m;

        int cost = play is null ? card.GetEnergyCostValueWithModifiers(context.Simulator)
            : play.IsAutoPlay ? play.Resources.EnergyValue : play.Resources.EnergySpent;
        return cost == 0 ? power.Amount : 0m;
    }

    private static decimal HandleFlutterPower""")
    state = source / "Search/SimulatedCombatState.cs"
    edit(state, "        afterAmountChanged?.Invoke(amount, simulated);",
         """        if (simulated is TankPower && previousAmount == 0 && simulated.Amount > 0)
        {
            foreach (Creature teammate in GetTeammatesOf(target).ToArray())
            {
                if (teammate != target && teammate.IsPlayer && (_predictionState?.GetCreature(teammate).IsAlive ?? teammate.IsAlive))
                    ApplyPowerFromSource(typeof(GuardedPower), teammate, simulated.Amount, target, null);
            }
        }
        afterAmountChanged?.Invoke(amount, simulated);""")
    # Removal uses the same power instance so Guarded from a second Tank stays intact.
    edit(state, "        if (mutable is ShowOffPower showOff",
         """        if (mutable is TankPower && previousAmount > 0 && mutable.Amount == 0)
        {
            foreach (GuardedPower guarded in EffectivePowers().OfType<GuardedPower>()
                         .Where(guarded => guarded.Applier == mutable.Owner
                             && guarded.Owner.Side == mutable.Owner.Side).ToArray())
                SetPowerAmount(guarded, 0);
        }
        if (mutable is ShowOffPower showOff""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.3b", subprocess=SimpleNamespace(run=stage)))()
