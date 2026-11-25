using System.Diagnostics;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record TapeResult(double WinProbability, double Unresolved, double ObservationsAccepted,
    int CompleteLaps, string Stop, HotCombatOutcome Outcome, int HpLost, int EnergyDelta,
    int Attempts, TraceStep[] Route);
internal sealed record Arrival(string Key, int Steps, int Turn, int HpLost, int EnergyDelta, int BlockDelta,
    int ExhaustDelta, double Weight, bool ReferenceMatch, object State, TraceStep[] Startup, TraceStep[] FirstPeriod);
internal sealed record JointBucket(string Status, string? Entry, int Actions, int Turn, int HpLost,
    int EnergyDelta, int Block, int EnemyHp, int Exhausted, bool FollowedPeriodActions, double Weight);
internal sealed record ArmResult(string Name, double Lower, double Upper, double EntryConfirmed,
    double EntryUnresolved, double Victory, double Death, double Unfinished, double Unresolved,
    double VictoryWithoutEntry, double VictoryAfterEntry, double VictoryWithPeriodActions,
    double? EntryWeightedContinuationUpper,
    int Nodes, int Attempts, int EntryAttempts, int AuditAttempts, int MaxActionDepth, int MaxEventDepth,
    double Milliseconds, IReadOnlyDictionary<string, int> SearchStops, BoundAction? FirstMove,
    Arrival[] Entries, JointBucket[] Joint, IReadOnlyDictionary<string, TraceStep[]> Samples, object[] Continuations);

internal sealed class ReachEvaluation(Session session, StructureTrace trace, ReachBudget budget, EntryTemplate[] templates)
{
    private const double Tolerance = 1e-9;
    public ArmResult Run(Snapshot root, string name, ReachGoal goal, bool ideal, string[] guide)
    {
        var clock = Stopwatch.StartNew();
        var entry = new EntryVerifier(session, trace, templates, budget.EntryAttempts);
        int horizon = goal == ReachGoal.Entry ? budget.StartActions : budget.BattleActions;
        var search = new ReachPolicySearch(session, trace, entry, budget, ideal, goal, guide).Solve(root, horizon);
        var audit = new PolicyAudit(session, trace);
        var arrivals = new Dictionary<string, Arrival>();
        var seen = new Dictionary<string, (Snapshot State, EntryResult Proof)>();
        var samples = new Dictionary<string, TraceStep[]>();
        var outcomes = new Dictionary<JointBucket, double>();
        var continuations = new Dictionary<string, (Bounds Value, object Report)>();
        var continuationAudit = new PolicyAudit(session, trace);
        var postEntryAudit = new List<object>();
        double entryMass = 0, entryUnknown = 0, win = 0, death = 0, ongoing = 0, unresolved = 0;
        double direct = 0, withEntry = 0, viaPeriod = 0, weightedLower = 0, weightedUpper = 0;

        audit.Run(root, search.Value.Policy, OnLeaf, ObserveState);
        void ObserveState(Snapshot state, int depth, double weight)
        {
            if (depth > budget.StartActions)
                return;
            string fingerprint = Key(state, depth);
            if (!seen.ContainsKey(fingerprint))
            {
                EntryResult proof = entry.Verify(state, budget.BattleActions - depth);
                seen.Add(fingerprint, (state, proof));
            }
        }

        void OnLeaf(PolicyLeaf leaf)
        {
            string routeKey = Key(root, 0);
            string? first = null;
            bool unknown = false;
            int entryDepth = 0;
            for (int i = 0; i <= Math.Min(leaf.Actions, budget.StartActions); i++)
            {
                if (i > 0)
                    routeKey = $"{i}:{leaf.Route[i - 1].StateKey}";
                if (!seen.TryGetValue(routeKey, out var found))
                    continue;
                if (found.Proof.Witness == null)
                {
                    unknown |= found.Proof.Unresolved != null;
                    continue;
                }
                first = routeKey;
                entryDepth = i;
                var proof = found.Proof.Witness;
                entryMass += leaf.Weight;
                if (arrivals.TryGetValue(first, out Arrival? arrival))
                    arrivals[first] = arrival with { Weight = arrival.Weight + leaf.Weight };
                else
                    arrivals.Add(first, new(first, i, found.State.State.PlayerTurnNumber,
                        root.State.Player.CurrentHp - found.State.State.Player.CurrentHp,
                        found.State.State.Energy - root.State.Energy, found.State.State.Player.Block - root.State.Player.Block,
                        found.State.State.ExhaustCount - root.State.ExhaustCount, leaf.Weight, proof.ReferenceMatch,
                        trace.Frame(found.State), leaf.Route.Take(i).ToArray(), proof.Period));
                break;
            }
            if (first == null && (unknown || ReachPolicySearch.Unresolved(leaf.Reason)))
                entryUnknown += leaf.Weight;
            if (goal == ReachGoal.Entry && !ReachPolicySearch.Unresolved(leaf.Reason) &&
                leaf.State.State.TerminalOutcome == HotCombatOutcome.Ongoing && leaf.Actions < budget.BattleActions)
            {
                string continuationKey = $"{Key(leaf.State, leaf.Actions)}:{leaf.Events}";
                if (!continuations.TryGetValue(continuationKey, out var continuation))
                {
                    string[] order = first == null ? [] : arrivals[first].FirstPeriod.Select(s => s.Move.Card).ToArray();
                    var suffix = new ReachPolicySearch(session, trace, entry, budget, ideal, ReachGoal.Victory, order)
                        .Solve(leaf.State, budget.BattleActions - leaf.Actions, leaf.Events);
                    var report = new { entry = first, At = leaf.Actions, suffix.Value.Lower, suffix.Value.Upper,
                        suffix.Attempts, suffix.Milliseconds, suffix.Stops };
                    continuation = (suffix.Value, report);
                    continuations.Add(continuationKey, continuation);

                    if (first != null)
                    {
                        var tape = FixedTape(leaf.State, arrivals[first].FirstPeriod, budget.BattleActions - leaf.Actions);
                        var idealSuffix = !ideal ? new ReachPolicySearch(session, trace, entry, budget, true,
                            ReachGoal.Victory, order).Solve(leaf.State, budget.BattleActions - leaf.Actions, leaf.Events) : suffix;
                        // Audit the ideal suffix too. Its branch weight is a possibility marker.
                        continuationAudit.Run(leaf.State, idealSuffix.Value.Policy, _ => { });
                        postEntryAudit.Add(new { entry = first, Fixed = tape,
                            Adaptive = new { suffix.Value.Lower, suffix.Value.Upper, suffix.Attempts, suffix.Milliseconds, suffix.Stops },
                            Ideal = new { idealSuffix.Value.Lower, idealSuffix.Value.Upper,
                                idealSuffix.Attempts, idealSuffix.Milliseconds } });
                    }
                }
                if (first != null)
                {
                    weightedLower += leaf.Weight * continuation.Value.Lower;
                    weightedUpper += leaf.Weight * continuation.Value.Upper;
                }
                continuationAudit.Run(leaf.State, continuation.Value.Policy, end =>
                {
                    AddOutcome(end with { Weight = end.Weight * leaf.Weight, Actions = end.Actions + leaf.Actions,
                        Route = [.. leaf.Route, .. end.Route] }, first, entryDepth, unknown);
                });
            }
            else
            {
                AddOutcome(leaf, first, entryDepth, unknown);
            }
        }

        void AddOutcome(PolicyLeaf leaf, string? first, int entryDepth, bool unknown)
        {
            bool followed = first != null && leaf.Route.Skip(entryDepth).Take(arrivals[first].FirstPeriod.Length)
                .Select(item => item.Move).SequenceEqual(arrivals[first].FirstPeriod.Select(item => item.Move));
            if (ReachPolicySearch.Unresolved(leaf.Reason))
                unresolved += leaf.Weight;
            else if (leaf.State.State.TerminalOutcome == HotCombatOutcome.Victory)
            {
                win += leaf.Weight;
                if (first != null)
                {
                    withEntry += leaf.Weight;
                    if (followed)
                        viaPeriod += leaf.Weight;
                }
                else if (!unknown)
                    direct += leaf.Weight;
            }
            else if (leaf.State.State.TerminalOutcome is HotCombatOutcome.Defeat or HotCombatOutcome.EventDefeat)
                death += leaf.Weight;
            else
                ongoing += leaf.Weight;
            string status = leaf.Reason;
            var bucket = new JointBucket(status, first, leaf.Actions, leaf.State.State.PlayerTurnNumber,
                root.State.Player.CurrentHp - leaf.State.State.Player.CurrentHp, leaf.State.State.Energy - root.State.Energy,
                leaf.State.State.Player.Block, leaf.State.State.Enemies[0].Vital.CurrentHp,
                leaf.State.State.ExhaustCount, followed, 0);
            outcomes[bucket] = outcomes.GetValueOrDefault(bucket) + leaf.Weight;
            samples.TryAdd(status, leaf.Route);
        }

        RequireClose(win + death + ongoing + unresolved, 1, "joint mass");
        RequireClose(goal == ReachGoal.Entry ? entryMass : win, search.Value.Lower, "audited lower");
        RequireClose(entryMass, arrivals.Values.Sum(row => row.Weight), "entry mass");
        if (goal == ReachGoal.Entry)
            RequireClose(withEntry, weightedLower, "joint startup and continuation victory");
        foreach (Arrival arrival in arrivals.Values)
        {
            Snapshot state = seen[arrival.Key].State;
            foreach (TraceStep planned in arrival.FirstPeriod)
            {
                Walk next = trace.Replay(state, planned, Mode.Ideal, () => true, strict: true);
                state = next.State ?? throw new InvalidOperationException($"Entry proof failed replay: {next.Stop}");
            }
        }
        clock.Stop();
        return new(name, search.Value.Lower, search.Value.Upper, entryMass, entryUnknown, win, death,
            ongoing, unresolved, direct, withEntry, viaPeriod, goal == ReachGoal.Entry ? weightedUpper : null,
            search.Nodes, search.Attempts, entry.Attempts,
            audit.Attempts + continuationAudit.Attempts, search.Depth, search.EventDepth,
            clock.Elapsed.TotalMilliseconds, search.Stops, (search.Value.Policy as Act)?.Move, arrivals.Values.ToArray(),
            outcomes.Select(item => item.Key with { Weight = item.Value }).ToArray(), samples,
            [.. continuations.Values.Select(data => data.Report), .. postEntryAudit]);
    }

    private static string Key(Snapshot state, int depth) => $"{depth}:{StructureTrace.ExactKey(state)}";

    public TapeResult FixedTape(Snapshot root, TraceStep[] period, int horizon)
    {
        Snapshot state = root;
        var actions = new List<TraceStep>();
        int tries = 0, loops = 0;
        double mass = 1;
        string reason = "action_horizon";
        for (int i = 0; i < horizon; i++)
        {
            Walk next = trace.Replay(state, period[i % period.Length], Mode.Ideal,
                () => ++tries <= budget.Attempts, strict: false);
            if (next.State == null)
            {
                reason = next.Stop!;
                break;
            }
            actions.Add(next.Step!);
            state = next.State;
            foreach (StepEvent step in next.Step!.Events)
            {
                if (step.Kind != EventKind.Draw)
                    continue;
                ushort representative = step.Options.Single(item => item.Instance == step.Result).Observation;
                mass *= ReachPolicySearch.Support(step).Single(option => option.Id == representative).Probability;
            }
            if ((i + 1) % period.Length == 0)
                loops++;
            if (state.State.TerminalOutcome == HotCombatOutcome.Ongoing)
                continue;
            reason = $"terminal:{state.State.TerminalOutcome}";
            break;
        }

        Snapshot check = root;
        foreach (TraceStep step in actions)
            check = trace.Replay(check, step, Mode.Ideal, () => true, strict: true).State!;
        return new(state.State.TerminalOutcome == HotCombatOutcome.Victory ? mass : 0,
            ReachPolicySearch.Unresolved(reason) || reason == "verification_budget" ? mass : 0,
            mass, loops, reason, state.State.TerminalOutcome, root.State.Player.CurrentHp - state.State.Player.CurrentHp,
            state.State.Energy - root.State.Energy, tries, actions.ToArray());
    }

    public static void RequireClose(double a, double b, string description)
    {
        if (Math.Abs(a - b) > Tolerance)
            throw new InvalidOperationException($"{description}: {a} vs expected {b}.");
    }
}
