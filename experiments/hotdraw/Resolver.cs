using System.Diagnostics;
using System.Runtime.InteropServices;
using CombatSolver.HotKernel;

namespace CombatSolver.HotDraw;

internal enum StepStatus { Completed, NeedsChoice, NeedsChance, Unsupported, Error }
internal enum EventKind { Draw, KnownDraw, Shuffle, PlayerChoice }

// Positions index one explicit transcript across two independent input channels.
internal sealed record EventAddress(int Position, EventKind Kind, string Source, string Phase, int Depth, int Remaining);
internal sealed record DrawInput(EventAddress Address, ushort Instance);
internal sealed record PlayerOption(HotChoiceKind Kind, ushort Instance);
internal sealed record ChoiceInput(EventAddress Address, PlayerOption Choice);
internal sealed record Prefix(DrawInput[] Draws, ChoiceInput[] Choices)
{
    public static readonly Prefix Empty = new([], []);
    public Prefix AddDraw(StepEvent step, ushort uid) => this with { Draws = [.. Draws, new(step.Address, uid)] };
    public Prefix AddChoice(StepEvent step, PlayerOption choice) =>
        this with { Choices = [.. Choices, new(step.Address, choice)] };
}

internal sealed record OutcomeOption(ushort Instance, int Denominator, ushort EquivalenceRepresentative = 0)
{
    public double Probability => 1.0 / Denominator;
    internal ushort Observation => EquivalenceRepresentative == 0 ? Instance : EquivalenceRepresentative;
}
internal sealed record StepEvent(int Position, EventKind Kind, string Source, string Phase, int DrawDepth,
    int Remaining, string Observation, OutcomeOption[] Options, PlayerOption[] Choices,
    ushort? Result = null, PlayerOption? Selection = null)
{
    internal EventAddress Address => new(Position, Kind, Source, Phase, DrawDepth, Remaining);
}
internal sealed class Boundary(StepStatus status, string reason, string point) : Exception(reason)
{
    public StepStatus Status { get; } = status;
    public string Point { get; } = point;
}

// Fixed-world capture/replay is a private audit. Only Public is used by NOSL/Ideal.
internal enum Resolution { Public, CaptureWorld, ReplayWorld }

internal sealed class Probe(HotRules rules, DrawBelief belief, Prefix prefix, string actionSource,
    Resolution resolution)
{
    [ThreadStatic] internal static Probe? Current;
    public DrawBelief Belief { get; private set; } = belief;
    public List<StepEvent> Events { get; } = [];
    private int drawCursor;
    private int choiceCursor;
    public int LogicalShuffleCalls { get; private set; }

    public void BeforeDraw(ref CombatHotState state, HotColdSidecar? cold, HotExecScratch scratch,
        bool opening, int remaining, string drawSource)
    {
        long start = Stopwatch.GetTimestamp();
        try
        {
            DrawOne(ref state, cold, scratch, opening, remaining, drawSource);
        }
        finally
        {
            BeliefTicks += Stopwatch.GetTimestamp() - start;
        }
    }

    public long BeliefTicks { get; private set; }

    private void DrawOne(ref CombatHotState state, HotColdSidecar? cold, HotExecScratch scratch,
        bool opening, int remaining, string drawSource)
    {
        var options = Belief.Options();
        bool ambiguous = options.Length > 1;
        if (ambiguous)
            IdentifyEquivalentCopies(in state, cold, options);
        int position = Events.Count;
        var entry = new StepEvent(position, ambiguous ? EventKind.Draw : EventKind.KnownDraw, $"{actionSource}/{drawSource}",
            opening ? "turn_start_draw" : "draw_cards", scratch.ActiveDrawDepth, remaining,
            "on_draw_to_hand", options, []);
        ushort selected;
        if (!ambiguous)
            selected = options[0].Instance;
        else if (resolution == Resolution.CaptureWorld)
            selected = state.Cards[state.DrawStart].CardUid;
        else if (drawCursor < prefix.Draws.Length && prefix.Draws[drawCursor].Address == entry.Address)
            selected = prefix.Draws[drawCursor++].Instance;
        else
        {
            RequireConsumed();
            Events.Add(entry);
            throw new Boundary(StepStatus.NeedsChance, "unknown_draw", "DrawCards");
        }

        if (!options.Any(option => option.Instance == selected))
            throw new InvalidOperationException($"Illegal draw instance at event {position}.");
        if (resolution != Resolution.Public && state.Cards[state.DrawStart].CardUid != selected)
            throw new InvalidOperationException($"Fixed world disagrees with draw at event {position}.");
        if (resolution == Resolution.Public)
        {
            var cards = MemoryMarshal.CreateSpan(ref state.Cards[state.DrawStart], state.DrawCount);
            int offset = 0;
            while (offset < cards.Length && cards[offset].CardUid != selected)
                offset++;
            if (offset == cards.Length)
                throw new InvalidOperationException("Bound draw instance does not exist.");
            HotCard card = cards[offset];
            cards[..offset].CopyTo(cards.Slice(1, offset));
            cards[0] = card;
        }
        Belief = Belief.Draw(selected);
        Events.Add(entry with { Result = selected });
    }

    // Output keeps each instance so a specific world and the full conditional tree can
    // both be replayed. Search uses a single continuation for provably identical copies.
    private static void IdentifyEquivalentCopies(in CombatHotState state, HotColdSidecar? cold, OutcomeOption[] options)
    {
        var positions = new Dictionary<ushort, int>(state.DrawCount);
        for (int i = state.DrawStart; i < state.DrawStart + state.DrawCount; i++)
            positions.Add(state.Cards[i].CardUid, i);
        var representatives = new List<OutcomeOption>();
        for (int i = 0; i < options.Length; i++)
        {
            var option = options[i];
            bool matched = false;
            foreach (var representative in representatives)
            {
                if (!HotCombatEngine.EquivalentResearchDraw(in state, cold,
                        positions[representative.Instance], positions[option.Instance]))
                    continue;
                options[i] = option with { EquivalenceRepresentative = representative.Instance };
                matched = true;
                break;
            }
            if (!matched)
                representatives.Add(option);
        }
    }

    public bool BeforeShuffle(in CombatHotState state, Span<HotCard> cards, HotRules? activeRules)
    {
        long start = Stopwatch.GetTimestamp();
        try
        {
            if (state.DrawCount != 0)
                Reject("non_empty_shuffle", "ShuffleDiscardIntoDraw");
            byte perfectFit = activeRules?.GetEnchantmentDefId(HotEnchantmentId.PerfectFit) ?? 0;
            var ids = new ushort[cards.Length];
            for (int i = 0; i < cards.Length; i++)
            {
                if (perfectFit != 0 && cards[i].EnchId == perfectFit)
                    Reject("perfect_fit", "ModifyShuffleOrder");
                ids[i] = cards[i].CardUid;
            }
            Belief = Belief.Shuffle(ids);
            Events.Add(new StepEvent(Events.Count, EventKind.Shuffle, actionSource, "shuffle_discard",
                0, 0, "membership_only", [], []));
            LogicalShuffleCalls++;
            if (resolution != Resolution.Public)
                return false;
            cards.Sort(static (a, b) => a.CardUid.CompareTo(b.CardUid));
            return true;
        }
        finally
        {
            BeliefTicks += Stopwatch.GetTimestamp() - start;
        }
    }

    public HotChoiceSelection Choose(in CombatHotState state, HotExecScratch scratch)
    {
        if (scratch.PendingChoiceKind is not (HotChoiceKind.HandCard or HotChoiceKind.DiscardPile or HotChoiceKind.ExhaustPile))
            Reject("unqualified_choice_scope", scratch.PendingChoiceKind.ToString());
        Span<HotChoiceSelection> buffer = stackalloc HotChoiceSelection[HotLimits.MaxCards + 1];
        int count = HotCombatEngine.EnumerateChoiceOptions(in state, null, rules, scratch, buffer);
        if (count == 0)
            throw new InvalidOperationException("No legal options for choice.");
        int position = Events.Count;
        var choices = new PlayerOption[count];
        for (int i = 0; i < count; i++)
            choices[i] = new PlayerOption(buffer[i].Kind, buffer[i].CardUidOrIndex);
        var entry = new StepEvent(position, EventKind.PlayerChoice, actionSource,
            scratch.PendingChoiceKind.ToString(), scratch.ActiveDrawDepth, 0, "player_prompt",
            [], choices);
        if (choiceCursor >= prefix.Choices.Length || prefix.Choices[choiceCursor].Address != entry.Address)
        {
            RequireConsumed();
            Events.Add(entry);
            throw new Boundary(StepStatus.NeedsChoice, "player_choice", "RequestChoice");
        }
        PlayerOption chosen = prefix.Choices[choiceCursor++].Choice;
        int index = Array.IndexOf(choices, chosen);
        if (index < 0)
            throw new InvalidOperationException($"Stale or illegal player choice at event {position}.");
        Events.Add(entry with { Selection = chosen });
        return buffer[index];
    }

    public void BeforeMove(in CombatHotState state, int index, HotPileKind source, HotPileKind destination,
        int offset)
    {
        long start = Stopwatch.GetTimestamp();
        try
        {
            if (source == HotPileKind.Draw)
                Reject("direct_draw_pile_move", "HotPiles.MoveCard");
            if (destination != HotPileKind.Draw)
                return;
            if (offset != 0 && offset != state.DrawCount)
                Reject("interior_draw_insertion", "HotPiles.MoveCard");
            Belief = Belief.Insert(state.Cards[index].CardUid, top: offset == 0);
        }
        finally
        {
            BeliefTicks += Stopwatch.GetTimestamp() - start;
        }
    }

    public void BeforeRemove(in CombatHotState state, int index)
    {
        if (HotPiles.PileOfIndex(in state, index) == HotPileKind.Draw)
            Reject("direct_draw_pile_remove", "HotPiles.RemoveCard");
    }

    public void BeforeRng()
    {
        if (resolution != Resolution.Public)
            return;
        string point = new StackTrace().GetFrames()
            .Select(frame => frame.GetMethod())
            .FirstOrDefault(method => method?.DeclaringType != typeof(Probe) && method?.DeclaringType != typeof(HotRng))
            ?.Name ?? "HotRng";
        Reject("unmodeled_rng", point);
    }

    public void RequireConsumed()
    {
        if (drawCursor != prefix.Draws.Length || choiceCursor != prefix.Choices.Length)
            throw new InvalidOperationException("Unexpected or unconsumed event prefix.");
    }

    public void Reject(string reason, string point)
        => throw new Boundary(StepStatus.Unsupported, reason, point);
}
