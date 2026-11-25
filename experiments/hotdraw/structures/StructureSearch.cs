using System.Diagnostics;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record StructureArm(int Nodes, int SearchAttempts, int SearchTransitions, int ReplayAttempts,
    int AnalysisAttempts, int OutsideAuditAttempts, int MaxActionDepth, int MaxEventDepth,
    double SearchAndAnalysisMs, double AnalysisMs, double ReplayMs, double AuditMs, string Stop,
    IReadOnlyDictionary<string, int> Boundaries, object? FirstStructure, StructureWitness[] Structures,
    TraceStep[]? WinningRoute);
internal sealed record SearchFrame(Snapshot State, TraceStep? Step, string Shape, int Events);

internal sealed class StructureSearch(Session session, StructureTrace trace, StructureBudget limit, Mode mode, bool active)
{
    private readonly Stopwatch clock = new();
    private readonly List<SearchFrame> path = [];
    private readonly List<StructureWitness> structures = [];
    private readonly HashSet<string> tested = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> boundaries = new(StringComparer.Ordinal);
    private TraceStep[]? win;
    private int searchNodes, searchAttempts, searchTransitions, replayAttempts, analysisAttempts, auditAttempts;
    private int maxDepth, maxEvents;
    private double replayMs, analysisMs, auditMs;
    private object? first;
    private string stop = "admitted_frontier_finished";

    public StructureArm Run(Snapshot root)
    {
        clock.Start();
        path.Add(new(root, null, trace.Shape(root), 0));
        Visit();
        if (!active && win != null)
        {
            var watch = Stopwatch.StartNew();
            double priorReplay = replayMs;
            Reconstruct(root, win, analysis: true, collect: true);
            analysisMs += watch.Elapsed.TotalMilliseconds - (replayMs - priorReplay);
        }
        clock.Stop();
        var audit = Stopwatch.StartNew();
        if (win != null)
            Reconstruct(root, win, analysis: false, collect: false);
        foreach (var witness in structures)
        {
            // Include the one observed cycle as well as all extension laps. Some
            // witnesses stop midway through their last cycle.
            Reconstruct(root, witness.Startup.Concat(witness.Laps.SelectMany(lap => lap.Steps)),
                analysis: false, collect: false);
        }
        auditMs = audit.Elapsed.TotalMilliseconds;
        return new(searchNodes, searchAttempts, searchTransitions, replayAttempts, analysisAttempts, auditAttempts,
            maxDepth, maxEvents, Math.Max(0, clock.Elapsed.TotalMilliseconds - replayMs), Math.Max(0, analysisMs),
            replayMs, auditMs, stop, boundaries, first, structures.ToArray(), win);
    }

    public StructureArm Analyze(Snapshot root, TraceStep[] route)
    {
        clock.Start();
        var watch = Stopwatch.StartNew();
        path.Add(new(root, null, trace.Shape(root), 0));
        Reconstruct(root, route, analysis: true, collect: true);
        analysisMs += watch.Elapsed.TotalMilliseconds - replayMs;
        clock.Stop();
        var audit = Stopwatch.StartNew();
        foreach (var witness in structures)
            Reconstruct(root, witness.Startup.Concat(witness.Laps.SelectMany(lap => lap.Steps)),
                analysis: false, collect: false);
        auditMs = audit.Elapsed.TotalMilliseconds;
        return new(0, 0, 0, replayAttempts, analysisAttempts, auditAttempts, maxDepth, maxEvents,
            Math.Max(0, clock.Elapsed.TotalMilliseconds - replayMs), analysisMs, replayMs, auditMs,
            "supplied_route", boundaries, first, structures.ToArray(), route);
    }

    private bool InsideBudget()
    {
        if (clock.Elapsed.TotalMilliseconds >= limit.Milliseconds)
            return Stop("time_budget");
        if (searchAttempts + replayAttempts + analysisAttempts >= limit.Attempts)
            return Stop("attempt_budget");
        return true;
    }

    private bool Stop(string reason)
    {
        stop = reason;
        return false;
    }

    private void Count(string reason) => boundaries[reason] = boundaries.GetValueOrDefault(reason) + 1;

    private bool Visit()
    {
        SearchFrame current = path[^1];
        int depth = path.Count - 1;
        maxDepth = Math.Max(maxDepth, depth);
        maxEvents = Math.Max(maxEvents, current.Events);
        if (current.State.State.TerminalOutcome != HotCombatOutcome.Ongoing)
        {
            Count($"terminal:{current.State.State.TerminalOutcome}");
            if (current.State.State.TerminalOutcome == HotCombatOutcome.Victory)
            {
                win ??= path.Skip(1).Select(frame => frame.Step!).ToArray();
                return !active;
            }
            return false;
        }

        if (!InsideBudget() || searchNodes >= limit.Nodes)
        {
            if (searchNodes >= limit.Nodes)
                Stop("node_budget");
            return true;
        }
        if (depth >= limit.Actions)
        {
            Count("action_horizon");
            return false;
        }

        searchNodes++;
        if (active)
        {
            long start = Stopwatch.GetTimestamp();
            double priorReplay = replayMs;
            bool exhaustedByReplay = Detect();
            analysisMs += (Stopwatch.GetTimestamp() - start) * 1000.0 / Stopwatch.Frequency - (replayMs - priorReplay);
            if (exhaustedByReplay || structures.Count >= limit.Candidates)
            {
                Count(exhaustedByReplay ? "verified_terminal_subtree_deferred" : "candidate_budget");
                return false;
            }
        }

        IEnumerable<SearchFrame> children = Children(current);
        if (active)
        {
            // The observed child's resources order the DFS. The projection
            // never removes or merges states.
            children = children.OrderByDescending(frame => Rank(current.State, frame.State)).ToArray();
        }
        bool any = false;
        foreach (SearchFrame child in children)
        {
            any = true;
            path.Add(child);
            bool end = Visit();
            path.RemoveAt(path.Count - 1);
            if (end)
                return true;
        }
        if (!any)
            Count("no_completed_child");
        return !InsideBudget();
    }

    private IEnumerable<SearchFrame> Children(SearchFrame parent)
    {
        foreach (HotAction action in session.Actions(parent.State, false))
        {
            foreach (SearchFrame frame in Expand(parent, action, Prefix.Empty))
                yield return frame;
            if (!InsideBudget())
                yield break;
        }
    }

    private IEnumerable<SearchFrame> Expand(SearchFrame parent, HotAction action, Prefix prefix)
    {
        if (!InsideBudget())
            yield break;
        searchAttempts++;
        var result = session.Advance(parent.State, action, prefix, mode == Mode.Oracle
            ? Resolution.CaptureWorld : Resolution.Public);
        if (result.Status == StepStatus.Error)
            throw new InvalidOperationException($"Search failed at {result.Point}: {result.Reason}");
        if (result.Status == StepStatus.Unsupported)
        {
            Count($"unsupported:{result.Point}:{result.Reason}");
            yield break;
        }
        int events = parent.Events + CountDraws(result.Events);
        if (events > limit.Events)
        {
            Count("event_budget");
            yield break;
        }
        if (result.Status == StepStatus.Completed)
        {
            searchTransitions++;
            var child = result.Child!;
            yield return new(child, trace.Record(parent.State, action, result), trace.Shape(child), events);
            yield break;
        }

        StepEvent current = result.Pending;
        var prefixes = result.Status == StepStatus.NeedsChoice
            ? current.Choices.Select(choice => prefix.AddChoice(current, choice))
            : current.Options.Select(option => option.Observation).Distinct()
                .Select(id => prefix.AddDraw(current, id));
        foreach (Prefix next in prefixes)
        {
            foreach (SearchFrame child in Expand(parent, action, next))
                yield return child;
            if (!InsideBudget())
                yield break;
        }
    }

    private long Rank(Snapshot first, Snapshot last)
    {
        var d = trace.Delta(first, last);
        return d.Drawn * 8L + d.Exhausted * 4L + d.Energy * 3L + d.PlayerPowerAmount * 2L;
    }

    private bool Detect()
    {
        if (!InsideBudget() || structures.Count >= limit.Candidates)
            return false;
        SearchFrame end = path[^1];
        if (end.State.State.TerminalOutcome != HotCombatOutcome.Ongoing)
            return false;

        for (int length = 1; length <= Math.Min(limit.Period, path.Count - 1); length++)
        {
            int start = path.Count - length - 1;
            SearchFrame beginning = path[start];
            if (end.Shape != beginning.Shape)
                continue;
            TraceStep[] startup = path.Skip(1).Take(start).Select(node => node.Step!).ToArray();
            TraceStep[] period = path.Skip(start + 1).Select(node => node.Step!).ToArray();
            string signature = CycleSignature(period);
            if (!tested.Add(signature))
                continue;
            int discoveredAtNodes = searchNodes;
            int discoveredAtAttempts = searchAttempts;
            int discoveredAtTransitions = searchTransitions;
            var witness = Verify(path[0].State, beginning.State, end.State, startup, period, beginning.Events);
            structures.Add(witness);
            if (witness.Kind is "productive" or "finite_resource" && witness.Grade != "candidate")
            {
                first ??= new { nodes = discoveredAtNodes, transitions = discoveredAtTransitions,
                    attempts = discoveredAtAttempts, verificationAttempts = replayAttempts,
                    milliseconds = clock.Elapsed.TotalMilliseconds };
            }
            if (witness.Outcome == HotCombatOutcome.Victory)
            {
                win ??= witness.Startup.Concat(witness.Laps.SelectMany(lap => lap.Steps)).ToArray();
                return true;
            }
            return false; // Prefer the shortest observed return at each endpoint.
        }
        return false;
    }

    private static string CycleSignature(TraceStep[] period)
    {
        string[] moves = period.Select(step =>
            $"{step.Move.Instance}@{step.Move.Target}:{step.Move.Kind}:" +
            string.Join(',', step.Events.Where(e => e.Kind is EventKind.Draw or EventKind.KnownDraw or EventKind.PlayerChoice)
                .Select(e => e.Selection?.Instance ?? e.Result ?? 0))).ToArray();
        for (int size = 1; size < moves.Length; size++)
        {
            if (moves.Length % size == 0 && !moves.Where((move, index) => move != moves[index % size]).Any())
            {
                moves = moves[..size];
                break;
            }
        }
        return Enumerable.Range(0, moves.Length).Select(index =>
            string.Join(";", moves.Skip(index).Concat(moves.Take(index)))).Min(StringComparer.Ordinal)!;
    }

    private StructureWitness Verify(Snapshot root, Snapshot beginning, Snapshot observedEnd,
        TraceStep[] startup, TraceStep[] period, int startEvents)
    {
        var watch = Stopwatch.StartNew();
        int beforeAttempts = replayAttempts;
        Snapshot state = beginning;
        int eventCount = startEvents;
        var laps = new List<Lap>();
        int peakPay = 0, entry = 0, nontrivial = 0, actions = startup.Length;
        double probability = 1;
        string reason = "repeat_horizon";
        string initialShape = trace.Shape(beginning);
        bool allReturned = true;
        int completeRounds = 0;
        int stagnant = 0;
        for (int i = 0; i < limit.Laps; i++)
        {
            Snapshot lapStart = state;
            var steps = new List<TraceStep>();
            foreach (TraceStep step in period)
            {
                if (actions >= limit.Actions || eventCount > limit.Events)
                {
                    reason = actions >= limit.Actions ? "action_horizon" : "event_budget";
                    break;
                }

                Walk outcome = trace.Replay(state, step, mode, ReplayAttempt, strict: i == 0);
                if (outcome.Stop != null)
                {
                    reason = outcome.Stop;
                    break;
                }
                TraceStep recorded = outcome.Step!;
                eventCount += CountDraws(recorded.Events);
                if (eventCount > limit.Events)
                {
                    reason = "event_budget";
                    break;
                }
                peakPay = Math.Max(peakPay, recorded.EnergyCost);
                entry = Math.Max(entry, recorded.EnergyCost + lapStart.State.Energy - state.State.Energy);
                foreach (StepEvent e in recorded.Events)
                {
                    if (e.Kind != EventKind.Draw || e.Result is not { } chosen)
                        continue;
                    ushort group = e.Options.Single(option => option.Instance == chosen).Observation;
                    double mass = e.Options.Where(option => option.Observation == group).Sum(option => option.Probability);
                    if (mass < 1 - 1e-12)
                    {
                        probability *= mass;
                        nontrivial++;
                    }
                }
                steps.Add(recorded);
                actions++;
                state = outcome.State!;
                if (state.State.TerminalOutcome != HotCombatOutcome.Ongoing)
                {
                    reason = $"terminal:{state.State.TerminalOutcome}";
                    break;
                }
            }
            bool complete = steps.Count == period.Length;
            if (steps.Count > 0)
                laps.Add(new(i + 1, steps.ToArray(), trace.Delta(lapStart, state), StructureTrace.ExactKey(state), complete));
            if (complete)
                completeRounds++;
            if (!complete || state.State.TerminalOutcome != HotCombatOutcome.Ongoing)
                break;
            if (trace.Shape(state) != initialShape)
            {
                allReturned = false;
                reason = "phase_or_pile_shape_changed";
                break;
            }
            ResourceDelta delta = laps[^1].Delta;
            stagnant = delta.EnemyDurabilityRemoved <= 0 && delta.PlayerPowerAmount <= 0 && delta.Energy <= 0 ? stagnant + 1 : 0;
            if (stagnant >= 4)
            {
                reason = "no_offensive_or_resource_progress_in_four_laps";
                break;
            }
        }

        bool productive = laps.Any(lap => lap.Delta.EnemyDurabilityRemoved > 0 ||
            lap.Delta.PlayerPowerAmount > 0 || lap.Delta.Energy > 0);
        bool finite = reason is "insufficient_energy" or "required_instance_not_in_hand" or "draw_blocked_by_power";
        string kind = productive ? finite ? "finite_resource" : "productive"
            : laps.Any(lap => lap.Delta.Block > 0) ? "block_only" : "no_scored_progress";
        string grade = state.State.TerminalOutcome != HotCombatOutcome.Ongoing && laps.Count >= 2
            ? "repeated_to_terminal" : completeRounds >= 2 && allReturned ? "finite_repetitions" : "candidate";
        var entrance = CheckEntryEnergy(beginning, period);
        var witness = new StructureWitness(grade, kind, startup, period, trace.Frame(beginning), trace.Frame(observedEnd),
            trace.Delta(root, beginning), laps.ToArray(), trace.Frame(state), reason, state.State.TerminalOutcome,
            peakPay, entry, entrance, probability, nontrivial, mode == Mode.Oracle ? "fixed_private_world" :
                nontrivial > 0 ? "conditioned_on_public_draws" : "no_unknown_result_specified",
            replayAttempts - beforeAttempts, watch.Elapsed.TotalMilliseconds);
        replayMs += watch.Elapsed.TotalMilliseconds;
        return witness with { ReplayMs = watch.Elapsed.TotalMilliseconds };
    }

    private EntryEnergyCheck CheckEntryEnergy(Snapshot beginning, TraceStep[] period)
    {
        int last = -1;
        for (int energy = 0; energy <= Math.Min(8, beginning.State.Energy); energy++)
        {
            CombatHotState adjusted = beginning.State;
            adjusted.Energy = energy;
            Snapshot state = new(in adjusted, beginning.Cold, beginning.Belief);
            bool completed = true;
            foreach (TraceStep template in period)
            {
                Walk result = trace.Replay(state, template, mode, ReplayAttempt, strict: false);
                if (result.Stop == "verification_budget")
                    return new(null, last, result.Stop);
                if (result.State == null || result.State.State.TerminalOutcome != HotCombatOutcome.Ongoing)
                {
                    completed = false;
                    break;
                }
                state = result.State;
            }
            last = energy;
            if (completed && trace.Shape(state) == trace.Shape(beginning))
                return new(energy, energy, "qualified_under_same_state_and_event_tape");
        }
        return new(null, last, "no_shape_return_in_tested_range");
    }

    private static int CountDraws(IEnumerable<StepEvent> events) =>
        events.Count(e => e.Kind == EventKind.Draw && e.Options.Select(option => option.Observation).Distinct().Skip(1).Any());

    private bool ReplayAttempt()
    {
        if (!InsideBudget())
            return false;
        replayAttempts++;
        return true;
    }

    private void Reconstruct(Snapshot root, IEnumerable<TraceStep> route, bool analysis, bool collect)
    {
        Snapshot state = root;
        if (collect)
        {
            path.Clear();
            path.Add(new(root, null, trace.Shape(root), 0));
        }
        foreach (TraceStep step in route)
        {
            Walk next = trace.Replay(state, step, mode, () =>
            {
                if (analysis && !InsideBudget())
                    return false;
                if (analysis)
                    analysisAttempts++;
                else
                    auditAttempts++;
                return true;
            }, strict: true);
            if (next.State == null && analysis && next.Stop == "verification_budget")
            {
                Count("analysis_budget");
                return;
            }
            state = next.State ?? throw new InvalidOperationException($"Witness cannot be reconstructed: {next.Stop}");
            if (collect)
            {
                path.Add(new(state, step, trace.Shape(state), path[^1].Events + CountDraws(step.Events)));
                Detect();
            }
        }
    }
}
