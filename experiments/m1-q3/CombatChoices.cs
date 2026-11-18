using System.Diagnostics;
using CombatSolver;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace OfflineSearchHarness;

internal sealed class CombatChoices(Player player, bool tactical, CombatState combat, bool verifyStamps) : ICardSelector
{
    private sealed record Contract(string Source, string Effect, int Minimum, bool Multiple);
    private static readonly Dictionary<string, Contract> Contracts = new()
    {
        ["BURNING_PACT"] = new("hand", "exhaust", 1, false),
        ["PURITY"] = new("hand", "exhaust", 0, true),
        ["BEGONE"] = new("hand", "transform", 1, false),
        ["DREDGE"] = new("discard", "retrieve", 1, true),
        ["HEADBUTT"] = new("discard", "topdeck", 1, false),
    };

    private string? _action;
    private int _step;
    private bool _active;
    private CardModel[]? _selected;
    private Contract? _contract;
    private int _minionStrikes;
    public bool Requested { get; private set; }
    public string? Failure { get; private set; }
    public double ObservationMs { get; private set; }
    public double DecisionMs { get; private set; }
    public List<object> Log { get; } = [];
    public List<object> StateChecks { get; } = [];

    public void Begin(int step, string? action)
    {
        if (_active || Requested) throw new InvalidOperationException("Choice transaction already open or failed");
        _step = step;
        _action = action;
        _active = true;
        _selected = null;
        _contract = null;
    }

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        long watch = Stopwatch.GetTimestamp();
        var cards = options.ToArray();
        var pcs = player.PlayerCombatState!;
        if (!_active || _selected != null || _action == null || !Contracts.TryGetValue(_action, out var contract))
            return Reject(cards, minSelect, maxSelect, "unknown_or_repeated_request");
        var pile = contract.Source == "hand" ? pcs.Hand.Cards : pcs.DiscardPile.Cards;
        bool legal = minSelect >= 0 && maxSelect >= minSelect && minSelect <= cards.Length
            && (contract.Multiple || maxSelect <= 1)
            && cards.Distinct(ReferenceEqualityComparer.Instance).Count() == cards.Length
            && cards.All(card => pile.Any(p => ReferenceEquals(p, card)));
        if (!legal)
            return Reject(cards, minSelect, maxSelect, "unexpected_choice_contract");

        var visible = cards.Select((card, index) => new Candidate(index, card.Id.Entry,
            card.CurrentUpgradeLevel, card.EnergyCost?.GetResolved() ?? 0, card.Type.ToString(),
            card.DynamicVars.Values.Where(v => v.Name.Equals("Damage", StringComparison.OrdinalIgnoreCase)).Sum(v => (int)v.BaseValue),
            card.DynamicVars.Values.Where(v => v.Name.Equals("Block", StringComparison.OrdinalIgnoreCase)).Sum(v => (int)v.BaseValue),
            CardChoiceSupport.ChoiceCardKey(card))).ToArray();
        ObservationMs += Stopwatch.GetElapsedTime(watch).TotalMilliseconds;
        watch = Stopwatch.GetTimestamp();
        int count = minSelect;
        var ordered = visible.OrderBy(v => v.Index);
        if (tactical)
        {
            bool remove = contract.Source == "hand";
            ordered = remove ? visible.OrderBy(Value).ThenBy(v => v.Index)
                : visible.OrderByDescending(Value).ThenBy(v => v.Index);
            if (contract.Minimum == 0)
                count = Math.Max(minSelect, Math.Min(Math.Min(maxSelect, cards.Length),
                    visible.Count(v => v.Type is "Status" or "Curse")));
        }
        var indexes = ordered.Take(count).Select(v => v.Index).ToArray();
        DecisionMs += Stopwatch.GetElapsedTime(watch).TotalMilliseconds;
        if (indexes.Length < minSelect || indexes.Length > maxSelect)
            throw new InvalidOperationException("Choice count outside native limits");
        _contract = contract;
        _selected = indexes.Select(index => cards[index]).ToArray();
        _minionStrikes = pcs.Hand.Cards.Count(c => c.Id.Entry == "MINION_STRIKE");
        Log.Add(new { step = _step, action = _action, contract.Source, contract.Effect, minSelect, maxSelect,
            allowEmpty = minSelect == 0, energy = pcs.Energy, turn = pcs.TurnNumber, candidates = visible, indexes });
        return Task.FromResult<IEnumerable<CardModel>>(_selected);
    }

    private sealed record Candidate(int Index, string Id, int Upgrade, int Cost, string Type, int Damage, int Block, string Key);

    private static int Value(Candidate card) => card.Type is "Status" or "Curse" ? -10000
        : 3 * card.Damage + 4 * card.Block + 5 * card.Upgrade - 3 * card.Cost
            + (card.Type == "Power" ? 15 : 0);

    private Task<IEnumerable<CardModel>> Reject(CardModel[] cards, int minSelect, int maxSelect, string reason)
    {
        Requested = true;
        Failure = reason;
        Log.Add(new { step = _step, action = _action, minSelect, maxSelect, reason,
            candidates = cards.Select((c, i) => new { index = i, id = c.Id.Entry }).ToArray() });
        return Task.FromException<IEnumerable<CardModel>>(new NotSupportedException(reason));
    }

    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        Requested = true;
        Failure = "unsupported_reward_choice";
        Log.Add(new { step = _step, action = _action, reason = Failure });
        throw new NotSupportedException(Failure);
    }

    public void Complete(bool completed, bool combatContinues)
    {
        if (!_active) throw new InvalidOperationException("No choice transaction");
        _active = false;
        var pcs = player.PlayerCombatState!;
        if (_selected != null && completed && !Requested && combatContinues)
        {
            bool effect = _contract!.Effect switch
            {
                "exhaust" => _selected.All(card => pcs.ExhaustPile.Cards.Any(c => ReferenceEquals(c, card))),
                "retrieve" => _selected.All(card => pcs.Hand.Cards.Any(c => ReferenceEquals(c, card))),
                "topdeck" => _selected.All(card => pcs.DrawPile.Cards.Take(1).Any(c => ReferenceEquals(c, card))),
                "transform" => pcs.Hand.Cards.Count(c => c.Id.Entry == "MINION_STRIKE") > _minionStrikes,
                _ => false,
            };
            StateChecks.Add(new { step = _step, action = _action, effect });
            if (!effect)
            {
                Requested = true;
                Failure = "unverified_choice_effect";
            }
        }

        if (verifyStamps && completed && !Requested && combatContinues)
        {
            string stamp = ContinuationStamp.CaptureLive(combat).StateText;
            string hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
                System.Text.Encoding.UTF8.GetBytes(stamp))).ToLowerInvariant();
            StateChecks.Add(new { step = _step, exactStateIncludingRng = hash });
        }
    }
}
