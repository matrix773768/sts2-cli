using System.Collections.Immutable;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Mirrors;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.ValueProps;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private sealed record PublicPower(string Id, int Amount);

    private static readonly HashSet<string> QualifiedPowers =
        ["STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "VULNERABLE_POWER", "FRAIL_POWER"];

    private static ImmutableArray<PublicPower> PublicPowers(SimulatedCombatState combat, Creature creature) =>
        combat.EffectivePowers().Where(p => ReferenceEquals(p.Owner, creature) && QualifiedPowers.Contains(p.Id.Entry))
            .OrderBy(p => p.Id.Entry, StringComparer.Ordinal).Select(p => new PublicPower(p.Id.Entry, p.Amount))
            .ToImmutableArray();

    private static ImmutableArray<string> CurrentIntents(SimulatedCombatState combat, Creature enemy) =>
        combat.CurrentMonsterMove(enemy).Move.Intents.Select(intent => intent.IntentType.ToString()).ToImmutableArray();

    private sealed record Preview(int? DamagePerHit, int? Hits, int? Block, int? Draw);

    private static object InvalidAction(string detail) => new { status = "invalid_action", detail };

    private static IEnumerable<(PublicCard?, PlanCardChoice?)> PublicChoices(
        CombatPredictionSimulator sim, PredictedCard played)
    {
        if (played.Preview.Id.Entry != "SURVIVOR" ||
            CardChoiceSupport.GetSpec(sim, played) is not
                { Effect: PlanChoiceEffect.Discard, SourcePile: PileType.Hand, MinCount: 1, MaxCount: 1 } spec)
        {
            yield return (null, null);
            yield break;
        }

        var source = spec.SourceCards.Where(c => !ReferenceEquals(c.Original, played.Original)).ToArray();
        var options = spec.Options.Where(c => !ReferenceEquals(c.Original, played.Original)).ToArray();
        if (options.Length == 0) yield return (null, null);
        for (int i = 0; i < options.Length; i++)
        {
            var picked = options[i];
            string key = CardChoiceSupport.ChoiceCardKey(picked);
            int sourceIndex = Array.IndexOf(source, picked);
            if (sourceIndex < 0) throw new NotSupportedException("Survivor candidate missing from current hand");
            int Occurrence(IEnumerable<PredictedCard> cards) =>
                cards.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key);
            var token = new PlanCardToken(picked.Preview.Id.Entry, picked.Preview.CurrentUpgradeLevel, key,
                Occurrence(source.Take(sourceIndex)), Occurrence(options.Take(i)), picked.Preview.Title);
            yield return (new(i, token.CardId, picked.Preview.CurrentUpgradeLevel),
                new(spec.Effect, spec.SourcePile, [token], ContextId: spec.ContextId));
        }
    }

    private ImmutableArray<int> CurrentAttackHits(CombatPredictionSimulator sim,
        SimulatedCombatState combat, Creature enemy) => combat.CurrentMonsterMove(enemy).AttackHits
        .Select(hit => (int)HookMirrors.ModifyDamage(sim, _player.Creature, enemy,
            hit.BaseDamage, ValueProp.Move, null, null)).ToImmutableArray();

    private static readonly HashSet<string> AttackPreviews =
        ["STRIKE_IRONCLAD", "STRIKE_SILENT", "BASH", "TWIN_STRIKE", "POMMEL_STRIKE", "SLICE", "SHIV"];
    private static readonly HashSet<string> BlockPreviews =
        ["DEFEND_IRONCLAD", "DEFEND_SILENT", "SURVIVOR", "SHRUG_IT_OFF", "FLAME_BARRIER", "DODGE_AND_ROLL"];

    private Preview? ImmediatePreview(CombatPredictionSimulator sim, PredictedCard card, Creature? target)
    {
        var model = card.Preview;
        int? damage = null, hits = null, block = null;
        if (target != null && AttackPreviews.Contains(model.Id.Entry))
        {
            damage = (int)HookMirrors.ModifyDamage(sim, target, _player.Creature,
                model.DynamicVars.Damage.BaseValue, model.DynamicVars.Damage.Props, card, null);
            hits = model.Id.Entry == "TWIN_STRIKE" ? 2 : 1;
        }
        if (BlockPreviews.Contains(model.Id.Entry))
            block = (int)HookMirrors.ModifyBlock(sim, _player.Creature, model.DynamicVars.Block.BaseValue,
                model.DynamicVars.Block.Props, card, null, out _);
        int? draw = model.Id.Entry is "SHRUG_IT_OFF" or "POMMEL_STRIKE"
            ? (int)model.DynamicVars.Values.Single(v => v.Name == "Cards").BaseValue : null;
        return damage.HasValue || block.HasValue || draw.HasValue ? new(damage, hits, block, draw) : null;
    }
}
