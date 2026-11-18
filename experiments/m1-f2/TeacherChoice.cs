using System.Text.Json;
using CombatSolver;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Actions;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;
using OfflineSearchHarness;

namespace Sts2Headless;

internal sealed class TeacherChoice(Player player, PlanCardChoice contract) : ICardSelector
{
    private CardModel? _selected;
    private object? _evidence;
    private string? _failure;

    internal static bool Supports(PlanAction action)
    {
        if (action.NestedChoices?.Count > 0 || action.TurnStartChoices?.Count > 0)
            return false;
        return action.Kind switch
        {
            PlanActionKind.EndTurn => action.Choice == null,
            PlanActionKind.PlayCard => action.Choice == null || SupportedCard(action.CardId, action.Choice),
            PlanActionKind.UsePotion => action.PotionSlot >= 0 && (action.PotionId switch
            {
                "BEETLE_JUICE" => action.TargetCombatId != null && action.Choice == null,
                "COLORLESS_POTION" => action.TargetCombatId == null &&
                    action.Choice is { } choice && ValidColorless(choice),
                _ => false,
            }),
            _ => false,
        };
    }

    private static bool SupportedCard(string source, PlanCardChoice choice) => source switch
    {
        "HEADBUTT" => Valid(choice, PlanChoiceEffect.MoveToDrawTop, PileType.Discard),
        "SURVIVOR" => Valid(choice, PlanChoiceEffect.Discard, PileType.Hand),
        _ => false,
    };

    private static bool ValidColorless(PlanCardChoice choice) =>
        Valid(choice, PlanChoiceEffect.GenerateToHand, PileType.None, "COLORLESS_POTION");

    private static bool Valid(PlanCardChoice choice, PlanChoiceEffect effect, PileType pile, string source = "") =>
        choice.Effect == effect && choice.SourcePile == pile && choice.Timing == PlanChoiceTiming.Action &&
        choice.Cards.Count == 1 && choice.SourceId == source && string.IsNullOrEmpty(choice.ContextId) &&
        choice.Cards[0] is { StateKey.Length: > 0, SourceOccurrence: >= 0, OptionOccurrence: >= 0 };

    internal static TeacherChoice? Bind(JsonElement action, Player player)
    {
        if (!action.TryGetProperty("choice", out var payload) || payload.ValueKind == JsonValueKind.Null)
            return null;
        var choice = payload.Deserialize<PlanCardChoice>(new JsonSerializerOptions
            { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower })!;
        string source = action.GetProperty("kind").GetString() == nameof(PlanActionKind.UsePotion) ?
            action.GetProperty("potion_id").GetString()! : action.GetProperty("card_id").GetString()!;
        if (!(SupportedCard(source, choice)
            || source == "COLORLESS_POTION" && ValidColorless(choice)))
            throw new NotSupportedException("Unsupported F2 choice action");
        return new(player, choice);
    }

    private CardModel Select(CardModel[] options, CardModel[] source, string surface)
    {
        if (_selected != null || _failure != null || options.Distinct(ReferenceEqualityComparer.Instance).Count() != options.Length)
            throw Reject("Unexpected repeated or duplicate candidates");
        var token = contract.Cards.Single();
        bool Matches(CardModel card) => card.Id.Entry == token.CardId &&
            card.CurrentUpgradeLevel == token.UpgradeLevel && CardChoiceSupport.ChoiceCardKey(card) == token.StateKey;
        var byOption = options.Where(Matches).Skip(token.OptionOccurrence).FirstOrDefault();
        var bySource = source.Where(Matches).Skip(token.SourceOccurrence).FirstOrDefault();
        if (byOption == null || !ReferenceEquals(byOption, bySource))
            throw Reject("Native option and source occurrence do not resolve to the same instance");
        if (contract.Effect == PlanChoiceEffect.GenerateToHand && options.Length != 3)
            throw Reject("Unexpected native colorless menu size");
        _selected = byOption;
        _evidence = new { surface, effect = contract.Effect.ToString(),
            option = Array.FindIndex(options, c => ReferenceEquals(c, byOption)),
            source_index = Array.FindIndex(source, c => ReferenceEquals(c, byOption)),
            selected = token, menu = options.Select(CardChoiceSupport.ChoiceCardKey).ToArray() };
        return byOption;
    }

    private InvalidOperationException Reject(string reason)
    {
        _failure = reason;
        return new InvalidOperationException(reason);
    }

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        if (maxSelect != 1 || minSelect != 1 && !(minSelect == 0 && contract.Effect == PlanChoiceEffect.GenerateToHand))
            throw Reject("Unexpected native choice count");
        var cards = options.ToArray();
        var pcs = player.PlayerCombatState!;
        var source = contract.Effect switch
        {
            PlanChoiceEffect.MoveToDrawTop => pcs.DiscardPile.Cards.ToArray(),
            PlanChoiceEffect.Discard => pcs.Hand.Cards.ToArray(),
            _ => cards,
        };
        return Task.FromResult<IEnumerable<CardModel>>([Select(cards, source, "cards")]);
    }

    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        if (contract.Effect != PlanChoiceEffect.GenerateToHand)
            throw Reject("Unexpected native reward choice");
        var cards = options.Select(o => o.Card).ToArray();
        return new CardRewardSelection { card = Select(cards, cards, "reward") };
    }

    internal object Verify()
    {
        var pcs = player.PlayerCombatState!;
        IEnumerable<CardModel> destination = contract.Effect switch
        {
            PlanChoiceEffect.MoveToDrawTop => pcs.DrawPile.Cards.Take(1),
            PlanChoiceEffect.Discard => pcs.DiscardPile.Cards,
            _ => pcs.Hand.Cards,
        };
        if (_failure != null || _selected == null || !destination.Any(c => ReferenceEquals(c, _selected)))
            throw new InvalidOperationException(_failure ?? "Choice callback or exact destination instance missing");
        return new { binding = _evidence, destination_verified = true };
    }
}

public partial class RunSimulator
{
    internal Dictionary<string, object?> UseF2ColorlessPotion(Player player, int slot, TeacherChoice selector)
    {
        if (!IsPlayPhase() || HasPendingSelection || slot < 0 || slot >= player.PotionSlots.Count
            || player.PotionSlots[slot] is not { } potion || potion.Id.Entry != "COLORLESS_POTION"
            || potion.TargetType != TargetType.AnyPlayer || !potion.IsValidTarget(player.Creature))
            return Error("Unexpected colorless potion slot, target or play phase");

        return WithF2Selector(player, selector, () =>
        {
            var action = new UsePotionAction(potion, player.Creature, true);
            bool canceled = false;
            action.BeforeCancelled += _ => canceled = true;
            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(action);
            WaitForActionExecutor();
            _syncCtx.Pump();
            if (action.Exception is { } exception)
                return ErrorWithTrace("Native colorless potion action failed", exception);
            if (canceled || action.State != GameActionState.Finished ||
                !action.CompletionTask.IsCompletedSuccessfully || HasPendingSelection || player.PotionSlots[slot] != null)
                return Error("Native colorless potion did not complete and clear its slot");
            return DetectDecisionPoint();
        });
    }
}
