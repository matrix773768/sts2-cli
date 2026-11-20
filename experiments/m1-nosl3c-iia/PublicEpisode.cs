using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private sealed record NoslCard(int Index, string Id, int Upgrade, int? Cost,
        string? Enchantment, int? EnchantmentAmount, string? Affliction, int? AfflictionAmount);

    private sealed record NoslAction(int Index, string Kind, int? Card = null, int? Target = null,
        int? Choice = null, string? ChoiceZone = null, int? Potion = null, int? Cost = null, Preview? Preview = null,
        int? StarCost = null, bool EnergyX = false, bool StarX = false);

    private NoslCard NoslInstance(PredictedCard card, int index, int? cost = null) =>
        new(index, card.Preview.Id.Entry, card.Preview.CurrentUpgradeLevel, cost,
            card.Preview.Enchantment?.Id.Entry, card.Preview.Enchantment?.Amount,
            card.Preview.Affliction?.Id.Entry, card.Preview.Affliction?.Amount);

    private static NoslCard[] PublicPile(IEnumerable<NoslCard> pile) =>
        pile.OrderBy(c => c.Id, StringComparer.Ordinal)
            .ThenBy(c => c.Upgrade).ThenBy(c => c.Enchantment, StringComparer.Ordinal)
            .ThenBy(c => c.EnchantmentAmount).ThenBy(c => c.Affliction, StringComparer.Ordinal)
            .ThenBy(c => c.AfflictionAmount).Select((c, i) => c with { Index = i }).ToArray();

    private static NoslCard NoslRow(PredictedCard c) => new(0, c.Preview.Id.Entry,
        c.Preview.CurrentUpgradeLevel, null, c.Preview.Enchantment?.Id.Entry, c.Preview.Enchantment?.Amount,
        c.Preview.Affliction?.Id.Entry, c.Preview.Affliction?.Amount);

    private static IEnumerable<(int? Index, string? Zone, PlanCardChoice? Token)> NoslChoices(
        CombatPredictionSimulator sim, PredictedCard played, int handIndex, NoslCard[] discard)
    {
        // These shapes have public candidates before play. Execution-time specs for
        // other choices can sample RNG or inspect hidden draw order.
        if (played.Preview.Id.Entry == "SURVIVOR")
        {
            foreach (var (choice, token) in PublicChoices(sim, played))
                yield return choice == null ? (null, null, null) :
                    (choice.Index + (choice.Index >= handIndex ? 1 : 0), "hand", token);
            yield break;
        }

        if (played.Preview.Id.Entry != "HEADBUTT" || discard.Length == 0)
        {
            yield return (null, null, null);
            yield break;
        }

        if (CardChoiceSupport.GetSpec(sim, played) is not
            { Effect: PlanChoiceEffect.MoveToDrawTop, SourcePile: PileType.Discard, MinCount: 1, MaxCount: 1 } spec ||
            spec.Options.Count != discard.Length)
            throw new NotSupportedException("Unexpected public discard selection shape");

        for (int i = 0; i < spec.Options.Count; i++)
        {
            var picked = spec.Options[i];
            string key = CardChoiceSupport.ChoiceCardKey(picked);
            int occurrence = spec.Options.Take(i).Count(c => CardChoiceSupport.ChoiceCardKey(c) == key);
            var token = new PlanCardToken(picked.Preview.Id.Entry, picked.Preview.CurrentUpgradeLevel, key,
                occurrence, occurrence, picked.Preview.Title);
            yield return (i, "discard", new(spec.Effect, spec.SourcePile, [token], ContextId: spec.ContextId));
        }
    }

    private object NoslTerminal(Node node) => new
    {
        turn = node.Frame.Turn, hp = node.Frame.Hp, max_hp = node.Frame.MaxHp,
        block = node.Frame.Block, energy = node.Frame.Energy, potions = node.Frame.Potions,
    };

    private object ObserveNosl(Node node)
    {
        var snapshot = node.State!;
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var pc = sim.State.GetPlayerCombatState(_player);
        var targets = combat.KnownEnemies.Where(e => sim.State.GetCreature(e).IsAlive).ToArray();
        if (targets.Any(e => !sim.State.IsHittable(e)))
            throw new NotSupportedException("Alive enemy without qualified target mapping");

        var actions = new List<NoslAction>();
        var moves = new List<Option>();
        void Add(NoslAction action, PlanAction plan)
        {
            actions.Add(action);
            moves.Add(new(plan, null));
        }

        var hand = pc.Hand.Cards;
        var discard = pc.DiscardPile.Cards.Select((c, i) => NoslInstance(c, i)).ToArray();
        for (int index = 0; index < hand.Count; index++)
        {
            var card = hand[index];
            if (!combat.CanPlayCard(sim, card, out int cost, out int stars))
                continue;
            var type = sim.GetTargetType(card);
            if (type is not (TargetType.AnyEnemy or TargetType.Self or TargetType.None or
                TargetType.AllEnemies or TargetType.RandomEnemy or TargetType.TargetedNoCreature))
                throw new NotSupportedException($"Unqualified card costs/target type: {type}, stars={stars}");
            var id = card.Preview.Id.Entry;
            var choiceEffect = CardChoiceSupport.GetPotentialEffect(sim, card);
            if (CardChoiceSupport.RequiresUnsupportedExistingChoice(card.Preview) ||
                choiceEffect.HasValue && id is not ("SURVIVOR" or "HEADBUTT"))
                throw new NotSupportedException($"Public choice menu unavailable: {id} ({choiceEffect})");

            string key = CardChoiceSupport.ChoiceCardKey(card);
            var previous = hand.Take(index);
            for (int slot = 0; slot < (type == TargetType.AnyEnemy ? targets.Length : 1); slot++)
            {
                int? target = type == TargetType.AnyEnemy ? slot : null;
                var enemy = target.HasValue ? targets[slot] : null;
                var plan = new PlanAction(PlanActionKind.PlayCard, snapshot.Turn,
                    CardId: id, CardOccurrence: previous.Count(c => c.Preview.Id.Entry == id),
                    TargetCombatId: enemy?.CombatId, CardStateKey: key,
                    CardStateOccurrence: previous.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key));
                var preview = ImmediatePreview(sim, card, enemy);
                foreach (var (choice, zone, token) in NoslChoices(sim, card, index, discard))
                {
                    var kind = zone switch
                    {
                        "hand" => "play_with_discard",
                        "discard" => "play_with_draw_top",
                        _ => "play_card",
                    };
                    Add(new(actions.Count, kind, index, target, choice, zone, Cost: cost, Preview: preview,
                        StarCost: stars, EnergyX: card.Preview.EnergyCost.CostsX, StarX: card.Preview.HasStarCostX),
                        plan with { Choice = token });
                }
            }
        }

        for (int slot = 0; slot < _player.PotionSlots.Count; slot++)
        {
            var potion = combat.GetPotionAtSlot(_player, slot);
            if (potion == null)
                continue;
            // Only the verified self-use potion is admitted to this public adapter.
            if (potion.Id.Entry != "FLEX_POTION" || potion.TargetType != TargetType.AnyPlayer)
                throw new NotSupportedException($"Public potion menu unavailable: {potion.Id.Entry}");
            if (combat.IsPotionAvailable(_player, slot) && potion.IsValidTarget(_player.Creature))
                Add(new(actions.Count, "use_potion", Potion: slot),
                    new(PlanActionKind.UsePotion, snapshot.Turn, PotionSlot: slot, PotionId: potion.Id.Entry));
        }
        Add(new(actions.Count, "end_turn"), new(PlanActionKind.EndTurn, snapshot.Turn));
        _episodeMenu = moves.ToArray();
        return new
        {
            schema = "sts2.nosl_observation.v2",
            turn = snapshot.Turn, hp = snapshot.PlayerHp, max_hp = node.Frame.MaxHp,
            block = snapshot.PlayerBlock, energy = snapshot.Energy, stars = pc.Stars, draw_count = pc.DrawPile.Cards.Count,
            hand = hand.Select((c, i) => NoslInstance(c, i, c.GetEnergyCostWithModifiers(sim, pc))).ToArray(),
            discard, exhaust = PublicPile(pc.ExhaustPile.Cards.Select(NoslRow)),
            deck = PublicPile(_player.Deck.Cards.Select(c => new NoslCard(0, c.Id.Entry, c.CurrentUpgradeLevel,
                null, c.Enchantment?.Id.Entry, c.Enchantment?.Amount, c.Affliction?.Id.Entry, c.Affliction?.Amount))),
            powers = PublicPowers(combat, _player.Creature), potions = node.Frame.Potions,
            relics = _player.Relics.Select(r => r.Id.Entry).Order(StringComparer.Ordinal).ToArray(),
            enemies = targets.Select((enemy, i) => new
            {
                index = i, hp = sim.State.GetCreature(enemy).CurrentHp,
                block = sim.State.GetCreature(enemy).Block, attack_hits = CurrentAttackHits(sim, combat, enemy),
                intents = CurrentIntents(combat, enemy), powers = PublicPowers(combat, enemy),
            }).ToArray(),
            actions,
        };
    }
}
