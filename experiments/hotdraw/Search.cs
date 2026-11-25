using System.Diagnostics;
using CombatSolver.HotKernel;

namespace CombatSolver.HotDraw;

internal enum Mode { Oracle, Nosl, Ideal }
internal sealed record Budget(int Nodes, int Actions, int Events, bool EndTurn = false, bool FixedHorizon = true);
internal sealed record Mass(double Success, double Failure, double Unresolved, double Upper)
{
    public static readonly Mass Win = new(1, 0, 0, 1);
    public static readonly Mass Loss = new(0, 1, 0, 0);
    public static readonly Mass Unknown = new(0, 0, 1, 1);
}
internal sealed record WitnessStep(string Action, StepEvent[] Events);
internal sealed record Value(Mass Mass, WitnessStep[]? Witness, string? Action = null);
internal sealed record ChanceLevel(int Nodes, int Edges, int InstanceEdges);
internal sealed record SearchResult(Value Best, IReadOnlyDictionary<string, Mass> RootActions,
    int Nodes, int Attempts, int Transitions, int Replays, int ActionDepth, int EventDepth,
    IReadOnlyDictionary<int, ChanceLevel> ChanceByDepth, IReadOnlyDictionary<int, int> ChanceWidths,
    IReadOnlyDictionary<string, int> Stops,
    double Milliseconds, double StepMilliseconds, double ReplayMilliseconds, double BeliefMilliseconds);

internal sealed class Search(Session session, Mode mode, Budget budget, Func<Snapshot, bool> goal,
    Func<StepEvent, bool>? idealize = null)
{
    private int nodes;
    private int attempts;
    private int transitions;
    private int replays;
    private int actionDepth;
    private int eventDepth;
    private long stepTicks;
    private long replayTicks;
    private long beliefTicks;
    private readonly Dictionary<int, ChanceLevel> chanceByDepth = [];
    private readonly Dictionary<int, int> widths = [];
    private readonly Dictionary<string, int> stops = [];
    private readonly Dictionary<string, Mass> rootActions = [];

    public SearchResult Run(Snapshot root)
    {
        long start = Stopwatch.GetTimestamp();
        Value best = Decision(root, 0, 0);
        static double Ms(long ticks) => ticks * 1000.0 / Stopwatch.Frequency;
        return new SearchResult(best, rootActions, nodes, attempts, transitions, replays, actionDepth, eventDepth,
            chanceByDepth, widths, stops, Ms(Stopwatch.GetTimestamp() - start), Ms(stepTicks), Ms(replayTicks), Ms(beliefTicks));
    }

    private Value Decision(Snapshot state, int depth, int events)
    {
        actionDepth = Math.Max(actionDepth, depth);
        if (goal(state))
            return new Value(Mass.Win, []);
        if (state.State.TerminalOutcome != HotCombatOutcome.Ongoing)
            return new Value(Mass.Loss, null);
        if (depth >= budget.Actions)
            return budget.FixedHorizon ? new Value(Mass.Loss, null) : Stop("action_budget");
        if (!Enter())
            return Stop("node_budget");
        var values = new List<Value>();
        foreach (HotAction action in session.Actions(state, budget.EndTurn))
        {
            string name = session.ActionName(state, action);
            Value value = Action(state, action, Prefix.Empty, depth, events, 0) with { Action = name };
            if (depth == 0)
                rootActions.Add(name, value.Mass);
            values.Add(value);
        }
        return Best(values);
    }

    private Value Action(Snapshot parent, HotAction action, Prefix prefix, int depth, int events, int pending)
    {
        if (!Enter())
            return Stop("node_budget");
        long start = Stopwatch.GetTimestamp();
        Resolution resolution = mode == Mode.Oracle ? Resolution.CaptureWorld : Resolution.Public;
        Transition result = session.Advance(parent, action, prefix, resolution);
        long elapsed = Stopwatch.GetTimestamp() - start;
        attempts++;
        stepTicks += elapsed;
        beliefTicks += result.BeliefTicks;
        if (pending > 0)
        {
            replays++;
            replayTicks += elapsed;
        }
        int observed = result.Events.Count(entry => entry.Kind == EventKind.Draw);
        eventDepth = Math.Max(eventDepth, events + observed);
        if (result.Status == StepStatus.Error)
            throw new InvalidOperationException($"Study transition failed at {result.Point}: {result.Reason}");
        if (result.Status == StepStatus.Unsupported)
            return Stop($"unsupported:{result.Point}:{result.Reason}");
        if (result.Status == StepStatus.Completed)
        {
            transitions++;
            Value next = Decision(result.Child!, depth + 1, events + observed);
            return next with { Witness = next.Witness == null ? null :
                [new WitnessStep(session.ActionName(parent, action), result.Events), .. next.Witness] };
        }
        StepEvent boundary = result.Pending;
        if (result.Status == StepStatus.NeedsChoice)
        {
            return Best(boundary.Choices.Select(choice =>
                Action(parent, action, prefix.AddChoice(boundary, choice), depth, events, pending + 1)));
        }
        if (events + observed > budget.Events)
            return Stop("event_budget");
        var observations = boundary.Options.GroupBy(option => option.Observation).ToArray();
        int level = events + observed;
        var count = chanceByDepth.GetValueOrDefault(level) ?? new ChanceLevel(0, 0, 0);
        chanceByDepth[level] = new ChanceLevel(count.Nodes + 1, count.Edges + observations.Length,
            count.InstanceEdges + boundary.Options.Length);
        widths[observations.Length] = widths.GetValueOrDefault(observations.Length) + 1;
        if (mode == Mode.Ideal && (idealize?.Invoke(boundary) ?? true))
        {
            return Best(observations.Select(observation =>
                Action(parent, action, prefix.AddDraw(boundary, observation.Key), depth, events, pending + 1)));
        }

        return Expectation(observations.Select(observation => (observation.Sum(option => option.Probability),
            Action(parent, action, prefix.AddDraw(boundary, observation.Key), depth, events, pending + 1))));
    }

    internal static Value Expectation(IEnumerable<(double Weight, Value Branch)> children)
    {
        double success = 0, failed = 0, unresolved = 0, upper = 0;
        WitnessStep[]? witness = null;
        foreach ((double weight, Value branch) in children)
        {
            success += weight * branch.Mass.Success;
            failed += weight * branch.Mass.Failure;
            unresolved += weight * branch.Mass.Unresolved;
            upper += weight * branch.Mass.Upper;
            witness ??= branch.Witness;
        }
        return new Value(new Mass(success, failed, unresolved, upper), witness);
    }

    private bool Enter()
    {
        if (nodes >= budget.Nodes)
            return false;
        nodes++;
        return true;
    }

    private Value Stop(string reason)
    {
        stops[reason] = stops.GetValueOrDefault(reason) + 1;
        return new Value(Mass.Unknown, null);
    }

    // Mass describes the chosen lower-bound strategy. The best upper bound can
    // come from a different action, which remains unresolved until expanded.
    internal static Value Best(IEnumerable<Value> children)
    {
        Value? best = null;
        double upper = 0;
        foreach (Value child in children)
        {
            if (best == null || child.Mass.Success > best.Mass.Success ||
                (child.Mass.Success == best.Mass.Success && child.Mass.Unresolved < best.Mass.Unresolved))
                best = child;
            upper = Math.Max(upper, child.Mass.Upper);
        }
        return best == null ? new Value(Mass.Loss, null) : best with { Mass = best.Mass with { Upper = upper } };
    }
}
