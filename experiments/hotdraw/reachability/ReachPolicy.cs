using System.Diagnostics;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record ReachBudget(int StartActions, int BattleActions, int Events, int Attempts,
    int EntryAttempts, int Milliseconds);
internal enum ReachGoal { Entry, Victory }
internal abstract record Policy;
internal sealed record Leaf(string Reason) : Policy;
internal sealed record Act(BoundAction Move, Policy Next) : Policy;
internal sealed record Commit(Policy Next) : Policy;
internal sealed record Pick(EventAddress Address, PlayerOption Option, Policy Next) : Policy;
internal sealed record Observe(EventAddress Address, bool Ideal, ObservationBranch[] Branches) : Policy;
internal sealed record ObservationBranch(ushort Instance, double Probability, Policy Next);
internal sealed record Bounds(double Lower, double Upper, Policy Policy);
internal sealed record PolicySearchResult(Bounds Value, int Nodes, int Attempts, int Depth, int EventDepth,
    int EntryAttempts, double Milliseconds, IReadOnlyDictionary<string, int> Stops);
internal sealed record PolicyLeaf(Snapshot State, double Weight, string Reason, int Actions,
    int Events, TraceStep[] Route);

internal sealed class ReachPolicySearch(Session session, StructureTrace trace, EntryVerifier entry, ReachBudget budget,
    bool ideal, ReachGoal goal, string[] guide)
{
    private Stopwatch clock = new();
    private int nodes, attempts, maxDepth, maxEvents;
    private readonly Dictionary<string, int> stops = [];
    private const double Epsilon = 1e-12;

    public PolicySearchResult Solve(Snapshot root, int horizon, int initialEvents = 0,
        bool verifyFutureEntry = true)
    {
        clock.Start();
        Bounds value = Search(root, 0, initialEvents, horizon, verifyFutureEntry);
        clock.Stop();
        return new(value, nodes, attempts, maxDepth, maxEvents, entry.Attempts,
            clock.Elapsed.TotalMilliseconds, stops);
    }

    private Bounds Search(Snapshot state, int depth, int events, int horizon, bool verifyFutureEntry)
    {
        maxDepth = Math.Max(maxDepth, depth);
        maxEvents = Math.Max(maxEvents, events);
        if (state.State.TerminalOutcome != HotCombatOutcome.Ongoing)
            return Known($"terminal:{state.State.TerminalOutcome}",
                goal == ReachGoal.Victory && state.State.TerminalOutcome == HotCombatOutcome.Victory);
        if (goal == ReachGoal.Entry && verifyFutureEntry)
        {
            var proof = entry.Verify(state, Math.Max(0, budget.BattleActions - depth));
            if (proof.Witness != null)
                return Known("entry", true);
            if (proof.Unresolved != null)
                return Unknown(proof.Unresolved);
        }
        if (depth == horizon)
            return Known("action_horizon", false);
        if (session.Actions(state, false) is not { Length: > 0 } actions)
            return Known("no_legal_action", false);
        if (Limit() is { } stop)
            return Unknown(stop);

        nodes++;
        IEnumerable<HotAction> ordered = guide.Length == 0 ? actions : actions.OrderByDescending(action =>
            trace.Bind(state, action).Card == guide[depth % guide.Length]);
        return Max(ordered.Select(action => WrapAction(state, action, depth, events, horizon, verifyFutureEntry)));
    }

    private Bounds WrapAction(Snapshot state, HotAction action, int depth, int events, int horizon,
        bool verifyFutureEntry)
    {
        var value = Resolve(state, action, Prefix.Empty, depth, events, horizon, verifyFutureEntry);
        return value with { Policy = new Act(trace.Bind(state, action), value.Policy) };
    }

    private Bounds Resolve(Snapshot state, HotAction action, Prefix prefix, int depth, int events,
        int horizon, bool verifyFutureEntry)
    {
        if (Limit() is { } stop)
            return Unknown(stop);
        attempts++;
        Transition step = session.Advance(state, action, prefix);
        if (step.Status == StepStatus.Error)
            throw new InvalidOperationException($"Policy search: {step.Point}: {step.Reason}");
        if (step.Status == StepStatus.Unsupported)
            return Unknown($"unsupported:{step.Point}:{step.Reason}");
        int consumed = Events(step.Events);
        if (step.Status == StepStatus.Completed)
        {
            Bounds child = Search(step.Child!, depth + 1, events + consumed, horizon, verifyFutureEntry);
            return child with { Policy = new Commit(child.Policy) };
        }
        StepEvent pending = step.Pending;
        if (step.Status == StepStatus.NeedsChoice)
        {
            return Max(pending.Choices.Select(option =>
            {
                Bounds child = Resolve(state, action, prefix.AddChoice(pending, option), depth, events, horizon, verifyFutureEntry);
                return child with { Policy = new Pick(pending.Address, option, child.Policy) };
            }));
        }
        if (events + consumed > budget.Events)
            return Unknown("event_budget");
        var support = Support(pending);
        if (ideal)
        {
            return Max(support.Select(item =>
            {
                Bounds child = Resolve(state, action, prefix.AddDraw(pending, item.Id), depth, events, horizon, verifyFutureEntry);
                return child with { Policy = new Observe(pending.Address, true, [new(item.Id, 1, child.Policy)]) };
            }));
        }

        double lower = 0, upper = 0;
        var branches = new List<ObservationBranch>(support.Length);
        foreach (var item in support)
        {
            Bounds child = Resolve(state, action, prefix.AddDraw(pending, item.Id), depth, events, horizon, verifyFutureEntry);
            lower += item.Probability * child.Lower;
            upper += item.Probability * child.Upper;
            branches.Add(new(item.Id, item.Probability, child.Policy));
        }
        return new(lower, upper, new Observe(pending.Address, false, branches.ToArray()));
    }

    private string? Limit() => clock.ElapsedMilliseconds >= budget.Milliseconds ? "time_budget" :
        attempts >= budget.Attempts ? "attempt_budget" : null;

    private Bounds Unknown(string reason)
    {
        stops[reason] = stops.GetValueOrDefault(reason) + 1;
        return new(0, 1, new Leaf(reason));
    }

    private static Bounds Known(string reason, bool success) => new(success ? 1 : 0, success ? 1 : 0, new Leaf(reason));

    private static Bounds Max(IEnumerable<Bounds> children)
    {
        Bounds? incumbent = null;
        double upper = 0;
        foreach (var candidate in children)
        {
            if (incumbent == null || candidate.Lower > incumbent.Lower + Epsilon ||
                (Math.Abs(candidate.Lower - incumbent.Lower) < Epsilon && incumbent.Upper > candidate.Upper + Epsilon))
                incumbent = candidate;
            upper = Math.Max(upper, candidate.Upper);
            if (incumbent.Lower >= 1 - Epsilon)
                return incumbent with { Upper = 1 };
        }
        return incumbent! with { Upper = upper };
    }

    internal static (ushort Id, double Probability)[] Support(StepEvent step) =>
        step.Options.GroupBy(option => option.Observation)
            .Select(group => (group.Key, group.Sum(option => option.Probability))).ToArray();

    internal static int Events(IEnumerable<StepEvent> events) =>
        events.Count(e => e.Kind == EventKind.Draw && Support(e).Length > 1);

    internal static bool Unresolved(string reason) =>
        reason.EndsWith("_budget", StringComparison.Ordinal) || reason.StartsWith("unsupported:", StringComparison.Ordinal);
}

internal sealed class PolicyAudit(Session session, StructureTrace trace)
{
    public int Attempts { get; private set; }

    public void Run(Snapshot root, Policy policy, Action<PolicyLeaf> onLeaf,
        Action<Snapshot, int, double>? onStable = null)
    {
        var route = new List<TraceStep>();
        Stable(root, policy, 1, 0);

        void Stable(Snapshot state, Policy current, double weight, int events)
        {
            onStable?.Invoke(state, route.Count, weight);
            if (current is Leaf leaf)
            {
                onLeaf(new(state, weight, leaf.Reason, route.Count, events, route.ToArray()));
                return;
            }
            if (current is not Act action)
                throw new InvalidOperationException("A stable policy must select a legal action.");
            var move = session.Actions(state, false).Single(candidate => trace.Bind(state, candidate) == action.Move);
            Continue(state, move, Prefix.Empty, action.Next, weight, events);
        }

        void Continue(Snapshot state, HotAction move, Prefix prefix, Policy current, double weight, int events)
        {
            // A budget leaf here stops before committing an incomplete action.
            if (current is Leaf { Reason: var reason } && ReachPolicySearch.Unresolved(reason))
            {
                onLeaf(new(state, weight, reason, route.Count, events, route.ToArray()));
                return;
            }
            Attempts++;
            Transition step = session.Advance(state, move, prefix);
            if (step.Status == StepStatus.Completed && current is Commit committed)
            {
                route.Add(trace.Record(state, move, step));
                Stable(step.Child!, committed.Next, weight, events + ReachPolicySearch.Events(step.Events));
                route.RemoveAt(route.Count - 1);
                return;
            }
            if (step.Status == StepStatus.NeedsChoice && current is Pick choice && choice.Address == step.Pending.Address &&
                step.Pending.Choices.Contains(choice.Option))
            {
                Continue(state, move, prefix.AddChoice(step.Pending, choice.Option), choice.Next, weight, events);
                return;
            }
            if (step.Status == StepStatus.NeedsChance && current is Observe observation && observation.Address == step.Pending.Address)
            {
                var support = ReachPolicySearch.Support(step.Pending);
                if (!observation.Ideal && !observation.Branches.Select(branch => (branch.Instance, branch.Probability)).SequenceEqual(support))
                    throw new InvalidOperationException("A NOSL policy must preserve the whole chance support.");
                foreach (var branch in observation.Branches)
                {
                    if (!support.Any(option => option.Id == branch.Instance))
                        throw new InvalidOperationException("Policy observation is unsupported.");
                    Continue(state, move, prefix.AddDraw(step.Pending, branch.Instance), branch.Next,
                        weight * branch.Probability, events);
                }
                return;
            }
            throw new InvalidOperationException($"Policy diverged at {step.Status}/{step.Reason}.");
        }
    }
}
