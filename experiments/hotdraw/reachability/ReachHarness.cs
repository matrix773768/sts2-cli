using System.Diagnostics;
using System.IO.Compression;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record ReachOptions(string Name, string Base, string Target, ReachBudget Budget,
    StructureBudget Discovery, string Evidence, bool Pair = false, bool Tape = false, bool Laps = false);
internal sealed record ReachArms(ArmResult Startup, ArmResult Fight, ArmResult Switch, ArmResult IdealStartup);

internal static partial class HotDrawHarness
{
    private static object RunReachability(string requestPath, UnattendedTestRequest request, HotRootBundle bundle)
    {
        using var setup = JsonDocument.Parse(File.ReadAllBytes(requestPath));
        var options = setup.RootElement.GetProperty("reachability").Deserialize<ReachOptions>(Json)!;
        using var packed = File.OpenRead(options.Evidence);
        using var uncompressed = new GZipStream(packed, CompressionMode.Decompress);
        using var old = JsonDocument.Parse(uncompressed);
        var saved = old.RootElement.GetProperty("results");
        string reference = options.Target switch
        {
            "core" => "core50",
            "energy" => "energy_limited",
            "conditioned" => "conditioned",
            _ => throw new InvalidOperationException($"Unknown target family {options.Target}.")
        };
        var witness = saved.GetProperty(reference).GetProperty("result").GetProperty("active")
            .GetProperty("Structures")[0];
        TraceStep[] period = ReadRoute(witness.GetProperty("Period"));
        var template = EntryVerifier.ReadTemplate(options.Target, witness, period);
        var session = new Session(bundle.Rules);
        var trace = new StructureTrace(session, bundle.Rules);
        var mapping = BindFixtureInstances(request, bundle);
        var draw = Enumerable.Range(bundle.RootState.HandCount + 1,
            request.Cards.Where(card => card.Pile == "Draw").Sum(card => card.Count)).Select(id => (ushort)id);
        var belief = DrawBelief.Create([], draw, []);
        var root = session.Open(bundle.RootState, bundle.RootCold, belief, mapping, true);

        var timer = Stopwatch.StartNew();
        var discovery = new StructureSearch(session, trace, options.Discovery, Mode.Ideal, active: true).Run(root);
        StructureWitness? alternative = discovery.Structures.FirstOrDefault(item =>
            item.Grade != "candidate" && item.Kind is "productive" or "finite_resource" &&
            !SameRoles(item.Period, period));
        // An alternative can order the unrestricted switch search. It does not silently redefine
        // the archived target against which startup and entry mass are reported.
        string[] guide = (alternative?.Period ?? period).Select(step => step.Move.Card).ToArray();
        var arms = RunArms(root, session, trace, template, options.Budget, guide);
        var evaluation = new ReachEvaluation(session, trace, options.Budget, [template]);
        object? tape = options.Tape ? CheckConditioned(root, witness, session, trace, template, evaluation, options.Budget) : null;
        TapeResult? laps = options.Laps ? evaluation.FixedTape(root, period, options.Budget.BattleActions) : null;
        object? pair = options.Pair ? CheckReachPair(bundle, root, mapping, belief, session, trace,
            template, options.Budget, options.Discovery, discovery, guide, arms) : null;
        object? budgetCheck = options.Pair ? CheckReachBudget(root, session, trace, template, options.Budget) : null;
        object? substitute = null;
        if (alternative != null)
        {
            JsonElement report = JsonSerializer.SerializeToElement(alternative, Json);
            var replacement = EntryVerifier.ReadTemplate("discovered_alternative", report, alternative.Period);
            var replacementEvaluation = new ReachEvaluation(session, trace, options.Budget, [replacement]);
            substitute = new
            {
                alternative.Kind, alternative.Grade, replacement,
                prefix = alternative.Startup, alternative.Stop,
                nosl = replacementEvaluation.Run(root, "substitute_startup", ReachGoal.Entry, false, guide)
            };
        }
        ValidateReach(options.Name, arms, laps);
        return new
        {
            options.Name, options.Base, options.Target, options.Budget, options.Discovery,
            PublicRoot = trace.Frame(root), RootKey = session.PublicKey(root),
            Template = template, arms, discovery, substitute, tape, laps, pair, budgetCheck,
            runtimeMs = timer.Elapsed.TotalMilliseconds
        };
    }

    private static TraceStep[] ReadRoute(JsonElement json) => json.Deserialize<TraceStep[]>(Json)!;

    private static bool SameRoles(TraceStep[] left, TraceStep[] right)
    {
        static IEnumerable<(string Card, int Count)> Counts(TraceStep[] route) => route
            .GroupBy(step => step.Move.Card).OrderBy(group => group.Key, StringComparer.Ordinal)
            .Select(group => (group.Key, group.Select(step => step.Move.Instance).Distinct().Count()));
        return Counts(left).SequenceEqual(Counts(right));
    }

    private static ReachArms RunArms(Snapshot root, Session session, StructureTrace trace,
        EntryTemplate template, ReachBudget budget, string[] guide)
    {
        var eval = new ReachEvaluation(session, trace, budget, [template]);
        return new(
            eval.Run(root, "startup_first", ReachGoal.Entry, ideal: false, guide: []),
            eval.Run(root, "fight_first", ReachGoal.Victory, ideal: false, guide: []),
            eval.Run(root, "switch", ReachGoal.Victory, ideal: false, guide: guide),
            eval.Run(root, "ideal_startup", ReachGoal.Entry, ideal: true, guide: guide));
    }

    private static object CheckConditioned(Snapshot root, JsonElement witness, Session session,
        StructureTrace trace, EntryTemplate template, ReachEvaluation evaluation, ReachBudget budget)
    {
        var startup = ReadRoute(witness.GetProperty("Startup"));
        var period = ReadRoute(witness.GetProperty("Period"));
        int horizon = witness.GetProperty("Laps").EnumerateArray().Sum(lap => lap.GetProperty("Steps").GetArrayLength());
        Snapshot entry = root;
        foreach (TraceStep step in startup)
            entry = trace.Replay(entry, step, Mode.Ideal, () => true, strict: true).State
                ?? throw new InvalidOperationException("Archived conditioned startup did not replay.");
        var fixedTape = evaluation.FixedTape(entry, period, horizon);
        ReachEvaluation.RequireClose(fixedTape.WinProbability, 1.0 / 128, "archived conditional tape");
        string[] guide = period.Select(step => step.Move.Card).ToArray();
        ReachBudget sameHorizon = budget with { BattleActions = horizon, StartActions = 0 };
        var continuation = new ReachEvaluation(session, trace, sameHorizon, [template]);
        var adaptive = continuation.Run(entry, "adaptive", ReachGoal.Victory, false, guide);
        var ideal = continuation.Run(entry, "ideal", ReachGoal.Victory, true, guide);
        Check(adaptive.Upper >= fixedTape.WinProbability && ideal.Upper >= adaptive.Lower,
            "Conditional interval contradicts replayable lower bound.");
        return new { horizon, startup, Entry = trace.Frame(entry), fixedTape, adaptive, ideal };
    }

    private static object CheckReachPair(HotRootBundle bundle, Snapshot root, Dictionary<ushort, ushort> mapping,
        DrawBelief belief, Session session, StructureTrace trace, EntryTemplate template, ReachBudget budget,
        StructureBudget discoveryBudget, StructureArm originalDiscovery, string[] guide, ReachArms original)
    {
        CombatHotState state = bundle.RootState;
        for (int i = 0; i < state.DrawCount / 2; i++)
        {
            int a = state.DrawStart + i, b = state.DrawStart + state.DrawCount - i - 1;
            (state.Cards[a], state.Cards[b]) = (state.Cards[b], state.Cards[a]);
        }
        for (int stream = 0; stream < HotLimits.MaxRngStreams; stream++)
            state.Rng[stream] = HotRng.CreateFromSeed((ulong)(8217 + stream));
        for (int i = 0; i < state.TotalCardCount; i++)
            state.Cards[i].CardUid += 100;
        var ids = mapping.ToDictionary(row => (ushort)(row.Key + 100), row => row.Value);
        Snapshot paired = session.Open(in state, bundle.RootCold, belief, ids, true);
        Check(session.PublicKey(root) == session.PublicKey(paired), "Public root identity changed.");
        var pairedDiscovery = new StructureSearch(session, trace, discoveryBudget, Mode.Ideal, active: true).Run(paired);
        string Evidence(StructureArm arm) => JsonSerializer.Serialize(arm.Structures.Select(item =>
            new { item.Grade, item.Startup, item.Period, item.Laps, item.Stop }), Json);
        Check(Evidence(originalDiscovery) == Evidence(pairedDiscovery), "Private information changed potential evidence.");
        var alternate = RunArms(paired, session, trace, template, budget, guide);
        int matched = 0;
        foreach (var (baseArm, pairedArm) in new[] { (original.Startup, alternate.Startup), (original.Fight, alternate.Fight),
                     (original.Switch, alternate.Switch), (original.IdealStartup, alternate.IdealStartup) })
        {
            string Fingerprint(ArmResult arm) => JsonSerializer.Serialize(new
            {
                arm.Lower, arm.Upper, arm.FirstMove, arm.Entries, arm.Joint, arm.Samples, arm.SearchStops
            }, Json);
            Check(Fingerprint(baseArm) == Fingerprint(pairedArm), "Private information changed public result.");
            matched++;
        }
        return new { equal = true, policies = matched, potentialMatches = true,
            privateRngStreamsReplaced = HotLimits.MaxRngStreams };
    }

    private static object CheckReachBudget(Snapshot root, Session session, StructureTrace trace,
        EntryTemplate template, ReachBudget budget)
    {
        var small = new ReachEvaluation(session, trace, budget with { Attempts = 2 }, [template]);
        var bound = small.Run(root, "attempt_cutoff", ReachGoal.Entry, false, []);
        Check(bound.Lower < bound.Upper && bound.Unresolved > 0, "Small budget did not retain unresolved mass.");
        return bound;
    }

    private static void ValidateReach(string name, ReachArms results, TapeResult? laps)
    {
        if (name == "core50")
        {
            ReachEvaluation.RequireClose(results.Startup.Lower, 1, "known entry");
            ReachEvaluation.RequireClose(results.Startup.VictoryAfterEntry, 1, "known deterministic victory");
        }
        if (name == "startup_unknown")
        {
            Check(results.Startup.Lower > 1.0 / 24, "Reachability did not use alternative observations.");
            Check(results.Startup.Entries.SelectMany(entry => entry.Startup).SelectMany(step => step.Events)
                .Where(e => e.Kind == EventKind.Draw && e.Position == 0).Select(e => e.Result).Distinct().Count() > 1,
                "Startup proof must include distinct first observations.");
        }
        if (name == "energy_limited")
            Check(laps is { CompleteLaps: 4, Stop: "insufficient_energy" }, "Energy-limited baseline changed.");
        if (name == "quick_kill")
            Check(results.Fight.Victory == 1 && results.Fight.VictoryWithPeriodActions == 0,
                "Fight comparison should retain direct kill.");
        if (name == "ordinary_direct")
            Check(results.Fight.VictoryWithoutEntry == 1 && results.Startup.EntryConfirmed == 0,
                "A direct win without an entry must remain a victory.");
        foreach (var arm in new[] { results.Startup, results.Fight, results.Switch, results.IdealStartup })
            Check(arm.Lower <= arm.Upper + 1e-9 && arm.Upper <= 1 + 1e-9, "Probability interval invalid.");
        Check(results.IdealStartup.Upper + 1e-9 >= results.Startup.Lower,
            "Ideal and supported NOSL startup bounds conflict.");
        Check(results.Fight.Upper + 1e-9 >= results.Switch.Lower && results.Switch.Upper + 1e-9 >= results.Fight.Lower,
            "Unrestricted win search and structure-guided search must have overlapping valid bounds.");
    }
}
