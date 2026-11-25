using System.Diagnostics;
using System.Text;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record StructureBudget(int Nodes, int Attempts, int Actions, int Events, int Milliseconds,
    int Period, int Laps, int Candidates);
internal sealed record BoundAction(HotActionKind Kind, ushort Instance, string Card, int Target);
internal sealed record TraceStep(BoundAction Move, StepEvent[] Events, int EnergyCost, string StateKey);
internal sealed record Walk(Snapshot? State, TraceStep? Step, string? Stop);
internal sealed record ResourceDelta(int Energy, int Hp, int Block, long EnemyDurabilityRemoved,
    int PlayerPowerAmount, int Drawn, int Shuffles, int Exhausted);
internal sealed record Lap(int Number, TraceStep[] Steps, ResourceDelta Delta, string EndKey, bool Complete);
internal sealed record EntryEnergyCheck(int? Minimum, int TestedThrough, string Stop);
internal sealed record StructureWitness(string Grade, string Kind, TraceStep[] Startup, TraceStep[] Period,
    object Start, object OneLapEnd, ResourceDelta StartupDelta, Lap[] Laps, object Last, string Stop,
    HotCombatOutcome Outcome, int PeakBoundaryPayment, int ObservedPaymentRequirement, EntryEnergyCheck EntryEnergy,
    double ConditionalTapeProbability, int NontrivialDraws, string RandomDependency, int StepAttempts,
    double ReplayMs);

internal sealed class StructureTrace(Session session, HotRules rules)
{
    public static string ExactKey(Snapshot snap)
    {
        CombatHotState state = snap.State;
        HotColdSidecar? cold = snap.Cold;
        Span<byte> bytes = stackalloc byte[HotLimits.MaxPackedStateBytes];
        int size = HotStatePacker.Pack(ref state, ref cold, bytes, canonicalize: false);
        DrawBelief belief = snap.Belief;
        return $"{HotHash.ComputeHash(bytes[..size], cold)}|{belief.Generation}:" +
            $"{string.Join(',', belief.Top)}/{string.Join(',', belief.Unknown)}/{string.Join(',', belief.Bottom)}";
    }

    public BoundAction Bind(Snapshot parent, HotAction action)
    {
        if (action.Kind != HotActionKind.PlayCard)
            return new(action.Kind, 0, "", action.TargetEnemySlot);
        HotCard card = parent.State.Cards[action.SlotOrHandIdx];
        return new(action.Kind, card.CardUid, rules.Cards[card.CardDefId].Entry, action.TargetEnemySlot);
    }

    public TraceStep Record(Snapshot parent, HotAction action, Transition transition) => new(
        Bind(parent, action), transition.Events, Cost(parent, action), ExactKey(transition.Child!));

    private int Cost(Snapshot state, HotAction action)
    {
        if (action.Kind != HotActionKind.PlayCard)
            return 0;
        ref readonly HotCard card = ref state.State.Cards[action.SlotOrHandIdx];
        return HotCombatEngine.GetEffectiveEnergyCost(in state.State, in card, state.Cold, rules);
    }

    public string Shape(Snapshot snapshot)
    {
        ref readonly CombatHotState state = ref snapshot.State;
        StringBuilder key = new();
        key.Append(state.PlayerTurnNumber).Append('/').Append(state.PlayerPhase);
        for (int i = 0; i < state.EnemyCount; i++)
            key.Append('|').Append(state.Enemies[i].CurrentMoveNode).Append('/').Append(state.Enemies[i].DeathPhase)
                .Append('/').Append((state.Enemies[i].Vital.Flags & HotCreatureFlags.Alive) != 0);
        foreach (HotPileKind zone in new[] { HotPileKind.Hand, HotPileKind.Discard, HotPileKind.Exhaust, HotPileKind.Play })
        {
            key.Append('|').Append(zone).Append(':');
            int start = HotPiles.ZoneStart(in state, zone);
            int count = HotPiles.ZoneCount(in state, zone);
            for (int i = 0; i < count; i++)
                key.Append(state.Cards[start + i].CardUid).Append(',');
        }
        key.Append('|').AppendJoin(',', snapshot.Belief.Top)
            .Append('|').AppendJoin(',', snapshot.Belief.Unknown)
            .Append('|').AppendJoin(',', snapshot.Belief.Bottom);
        for (int i = 0; i < state.PowerCount; i++)
            key.Append('|').Append(state.Powers[i].PowerDefId).Append('@').Append(state.Powers[i].OwnerSlot);
        return key.ToString();
    }

    public object Frame(Snapshot frame)
    {
        CombatHotState state = frame.State;
        var powers = new List<object>();
        for (int i = 0; i < state.PowerCount; i++)
        {
            var p = state.Powers[i];
            powers.Add(new { id = rules.Powers[p.PowerDefId].Entry, p.OwnerSlot, p.ApplierSlot, p.TargetSlot,
                p.AuxCardUid, p.Amount, p.AmountOnTurnStart, p.Aux0, p.Aux1 });
        }
        var relics = new List<object>();
        foreach (ushort defId in rules.ActiveRelicDefIds)
        {
            if (rules.RelicDefIdToStateSlot.TryGetValue(defId, out byte slot))
            {
                var relic = state.RelicStates[slot];
                relics.Add(new { id = rules.Relics[defId].Entry, relic.Current, relic.PreviousOrAux });
            }
        }
        var counters = new int[64];
        for (int i = 0; i < counters.Length; i++)
            counters[i] = state.Counters[i];
        using var projection = System.Text.Json.JsonDocument.Parse(session.PublicJson(frame));
        return new { key = ExactKey(frame), state = projection.RootElement.Clone(), audit = new
        {
            powers, relics, counters, state.HistoryCardsDrawn, state.ShuffleEventCount, state.HistoryFinishedPlays,
            state.HistoryCourseUid
        } };
    }

    public ResourceDelta Delta(Snapshot first, Snapshot last) => new(last.State.Energy - first.State.Energy,
        last.State.Player.CurrentHp - first.State.Player.CurrentHp, last.State.Player.Block - first.State.Player.Block,
        Durability(first) - Durability(last), PowerAmount(last) - PowerAmount(first),
        last.State.HistoryCardsDrawn - first.State.HistoryCardsDrawn,
        last.State.ShuffleEventCount - first.State.ShuffleEventCount, last.State.ExhaustCount - first.State.ExhaustCount);

    private static long Durability(Snapshot state)
    {
        long value = 0;
        for (int i = 0; i < state.State.EnemyCount; i++)
        {
            var target = state.State.Enemies[i].Vital;
            if ((target.Flags & HotCreatureFlags.Alive) != 0)
                value += Math.Max(0, target.CurrentHp) + (long)target.Block;
        }
        return value;
    }

    private int PowerAmount(Snapshot state)
    {
        int value = 0;
        for (int i = 0; i < state.State.PowerCount; i++)
        {
            var power = state.State.Powers[i];
            if (power.OwnerSlot == 0 && rules.Powers[power.PowerDefId].Type == MegaCrit.Sts2.Core.Entities.Powers.PowerType.Buff)
                value += power.Amount;
        }
        return value;
    }

    public Walk Replay(Snapshot parent, TraceStep template, Mode mode, Func<bool> attempt, bool strict)
    {
        var expected = template.Move;
        HotAction? legal = session.Actions(parent, false)
            .Where(action => Bind(parent, action) == expected).Select(action => (HotAction?)action).SingleOrDefault();
        if (legal == null)
            return new(null, null, ExplainIllegal(parent, expected));

        StepEvent[] draws = template.Events.Where(IsDraw).ToArray();
        StepEvent[] choices = template.Events.Where(e => e.Kind == EventKind.PlayerChoice).ToArray();
        Prefix prefix = Prefix.Empty;
        for (;;)
        {
            if (!attempt())
                return new(null, null, "verification_budget");
            Transition result = session.Advance(parent, legal.Value, prefix, mode == Mode.Oracle
                ? Resolution.CaptureWorld : Resolution.Public);
            if (result.Status == StepStatus.Completed)
            {
                TraceStep step = Record(parent, legal.Value, result);
                if (strict)
                {
                    if (!step.Events.Select(EventKey).SequenceEqual(template.Events.Select(EventKey))
                        || step.EnergyCost != template.EnergyCost || step.StateKey != template.StateKey)
                        throw new InvalidOperationException("Exact witness replay diverged.");
                }
                else
                {
                    var actual = result.Events.Where(IsDraw).ToArray();
                    if (actual.Length < draws.Length && result.Outcome == HotCombatOutcome.Ongoing && NoDraw(parent))
                        return new(null, null, "draw_blocked_by_power");
                    if (actual.Length > draws.Length ||
                        actual.Where((e, i) => e.Result != draws[i].Result || !SameSite(e, draws[i])).Any())
                        return new(null, null, "draw_result_or_site_changed");
                    if (result.Outcome == HotCombatOutcome.Ongoing &&
                        (actual.Length != draws.Length || result.Events.Count(e => e.Kind == EventKind.PlayerChoice) != choices.Length))
                        return new(null, null, "missing_draw_or_choice");
                    var scripted = template.Events.Where(e => e.Kind != EventKind.Shuffle).ToArray();
                    var executed = result.Events.Where(e => e.Kind != EventKind.Shuffle).ToArray();
                    if (executed.Length > scripted.Length || executed.Where((e, i) =>
                        !SameSite(e, scripted[i]) || e.Result != scripted[i].Result || e.Selection != scripted[i].Selection).Any())
                        return new(null, null, "event_interleaving_changed");
                }
                return new(result.Child, step, null);
            }
            if (result.Status == StepStatus.Unsupported)
                return new(null, null, $"unsupported:{result.Point}:{result.Reason}");
            if (result.Status == StepStatus.Error)
                throw new InvalidOperationException($"Witness replay error at {result.Point}: {result.Reason}");

            StepEvent pending = result.Pending;
            if (result.Status == StepStatus.NeedsChoice)
            {
                int index = result.Events.Count(e => e.Kind == EventKind.PlayerChoice) - 1;
                if (index >= choices.Length || choices[index].Selection is not { } pick ||
                    !pending.Choices.Contains(pick) || !SameSite(pending, choices[index]))
                    return new(null, null, "choice_no_longer_legal");
                prefix = prefix.AddChoice(pending, pick);
            }
            else
            {
                int index = result.Events.Count(IsDraw) - 1;
                if (index >= draws.Length || draws[index].Result is not { } pick ||
                    !pending.Options.Any(option => option.Instance == pick) || !SameSite(pending, draws[index]))
                    return new(null, null, "required_draw_unavailable");
                prefix = prefix.AddDraw(pending, pick);
            }
        }
    }

    private static bool SameSite(StepEvent a, StepEvent b) =>
        a.Source == b.Source && a.Phase == b.Phase && a.DrawDepth == b.DrawDepth && a.Remaining == b.Remaining;

    private static bool IsDraw(StepEvent e) => e.Kind is EventKind.Draw or EventKind.KnownDraw;

    private static string EventKey(StepEvent e) => System.Text.Json.JsonSerializer.Serialize(e);

    private bool NoDraw(Snapshot state)
    {
        for (int i = 0; i < state.State.PowerCount; i++)
        {
            var p = state.State.Powers[i];
            if (p.OwnerSlot == 0 && p.Amount > 0 && rules.Powers[p.PowerDefId].Entry == "NO_DRAW_POWER")
                return true;
        }
        return false;
    }

    private string ExplainIllegal(Snapshot state, BoundAction move)
    {
        if (move.Kind != HotActionKind.PlayCard)
            return "action_not_legal";
        for (int i = 0; i < state.State.HandCount; i++)
        {
            ref readonly HotCard card = ref state.State.Cards[i];
            if (card.CardUid != move.Instance)
                continue;
            return HotCombatEngine.GetEffectiveEnergyCost(in state.State, in card, state.Cold, rules) > state.State.Energy
                ? "insufficient_energy" : "cost_phase_target_or_other_legality";
        }
        return "required_instance_not_in_hand";
    }
}
