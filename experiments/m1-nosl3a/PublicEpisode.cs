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
        int? Choice = null, int? Potion = null, int? Cost = null, Preview? Preview = null);

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
        for (int index = 0; index < hand.Count; index++)
        {
            var card = hand[index];
            if (!combat.CanPlayCard(sim, card, out int cost, out int stars))
                continue;
            var type = sim.GetTargetType(card);
            if (stars != 0 || type is not (TargetType.AnyEnemy or TargetType.Self or TargetType.None or
                TargetType.AllEnemies or TargetType.RandomEnemy or TargetType.TargetedNoCreature))
                throw new NotSupportedException($"Unqualified card costs/target type: {type}, stars={stars}");
            var id = card.Preview.Id.Entry;
            var choiceEffect = CardChoiceSupport.GetPotentialEffect(sim, card);
            if (choiceEffect.HasValue && id != "SURVIVOR")
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
                foreach (var (choice, token) in PublicChoices(sim, card))
                {
                    // N2A.1 choices use the hand after removal of the played instance.
                    int? picked = choice == null ? null : choice.Index + (choice.Index >= index ? 1 : 0);
                    Add(new(actions.Count, picked.HasValue ? "play_with_discard" : "play_card",
                        index, target, picked, Cost: cost, Preview: preview), plan with { Choice = token });
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
            turn = snapshot.Turn, hp = snapshot.PlayerHp, max_hp = node.Frame.MaxHp,
            block = snapshot.PlayerBlock, energy = snapshot.Energy, draw_count = pc.DrawPile.Cards.Count,
            hand = hand.Select((c, i) => NoslInstance(c, i, c.GetEnergyCostWithModifiers(sim, pc))).ToArray(),
            discard = PublicPile(pc.DiscardPile.Cards.Select(NoslRow)), exhaust = PublicPile(pc.ExhaustPile.Cards.Select(NoslRow)),
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
