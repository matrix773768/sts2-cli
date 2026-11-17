using CombatSolver;
using MegaCrit.Sts2.Core.Combat;
using System.Runtime.Loader;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using CombatSolver.Engine.InCombat.Simulation;
using HarmonyLib;

namespace Sts2Headless;

internal static class IntegrationProbe
{
    internal static Dictionary<string, object?> Run(RunSimulator sim, JsonElement cmd)
    {
        if (!_loaded) Load();
        var response = Dispatch(sim, cmd);
        using var process = Process.GetCurrentProcess();
        response["peak_working_set_bytes"] = process.PeakWorkingSet64;
        return response;
    }

    private static bool _loaded;
    private static void Load()
    {
        string solver = Environment.GetEnvironmentVariable("I1_SOLVER")!;
        AssemblyLoadContext.Default.Resolving += (context, name) =>
        {
            if (!(name.Name ?? "").StartsWith("STS2-RitsuLib", StringComparison.Ordinal)) return null;
            string root = Environment.GetEnvironmentVariable("I1_RITSU")!;
            foreach (string sub in new[] { "compat/0.113.0", "shared", "" })
            {
                string path = Path.Combine(root, sub, name.Name + ".dll");
                if (File.Exists(path)) return context.LoadFromAssemblyPath(path);
            }
            return null;
        };
        AssemblyLoadContext.Default.LoadFromAssemblyPath(solver);
        _loaded = true;
    }

    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static Dictionary<string, object?> Dispatch(RunSimulator sim, JsonElement cmd)
    {
        var watch = Stopwatch.StartNew();
        var live = CombatManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("No live combat");
        var player = live.Players.Single();
        switch (cmd.GetProperty("cmd").GetString())
        {
            case "i1_begin":
                if (_nativeCapture != null) throw new InvalidOperationException("Replay already started");
                var enemies = live.Enemies.ToArray();
                _nativeCapture = () => enemies.Select(enemy =>
                    Actual.Invoke(null, new object[] { live, player, enemy })).ToArray();
                var method = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
                    .Single(m => m.Name == "EndCombatInternal" && m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
                new Harmony("m1-i1.capture-terminal").Patch(method,
                    prefix: new HarmonyMethod(Private(typeof(IntegrationProbe), nameof(ObserveTerminal))));
                return new() { ["type"] = "i1_state", ["state"] = _nativeCapture() };
            case "i1_step":
                if (_nativeCapture == null || _terminal != null) throw new InvalidOperationException("Not in replay");
                var action = cmd.GetProperty("action");
                if (player.PlayerCombatState!.TurnNumber != action.GetProperty("turn").GetInt32())
                    throw new InvalidOperationException("Turn differs");
                var args = new Dictionary<string, object?>();
                string kind = action.GetProperty("kind").GetString()!;
                if (kind == "PlayCard")
                {
                    string id = action.GetProperty("card_id").GetString()!;
                    var hand = player.PlayerCombatState.Hand.Cards;
                    string key = action.GetProperty("card_state_key").GetString()!;
                    var matching = Enumerable.Range(0, hand.Count).Where(i => hand[i].Id.Entry == id);
                    var cardIndex = key.Length == 0
                        ? matching.ElementAt(action.GetProperty("card_occurrence").GetInt32())
                        : matching.Where(i => CardChoiceSupport.ChoiceCardKey(hand[i]) == key)
                            .ElementAt(action.GetProperty("card_state_occurrence").GetInt32());
                    var card = hand[cardIndex];
                    args["card_index"] = cardIndex;
                    MegaCrit.Sts2.Core.Entities.Creatures.Creature? target = null;
                    if (action.TryGetProperty("target_combat_id", out var targetId))
                    {
                        var alive = live.Enemies.Where(e => e.IsAlive).ToList();
                        var targetIndex = alive.FindIndex(e => e.CombatId == targetId.GetUInt32());
                        if (targetIndex < 0) throw new InvalidOperationException("Missing target");
                        args["target_index"] = targetIndex;
                        target = alive[targetIndex];
                    }
                    if (!card.CanPlayTargeting(target)) throw new InvalidOperationException("Illegal card or target");
                }
                else if (kind != "EndTurn") throw new InvalidOperationException("Unsupported action");
                var decision = sim.ExecuteAction(kind == "EndTurn" ? "end_turn" : "play_card", args);
                return new() { ["type"] = "i1_state", ["state"] = _terminal ?? _nativeCapture(),
                    ["terminal"] = _terminal != null, ["decision"] = decision };
            case "i1_state": return new() { ["type"] = "i1_state", ["state"] = _nativeCapture!() };
            case "i1_capture": break;
            default: throw new InvalidOperationException("Unknown probe command");
        }
        var root = CombatRootSnapshot.Capture(live);
        var names = SolverDisplayNames.Capture(live);
        if (Entry.Logger == null)
            typeof(Entry).GetProperty("Logger")!.SetValue(null, new CombatSolverLog(
                Environment.GetEnvironmentVariable("I1_LOG")!));
        var damage = BattleDamageTracker.Observe(live);
        var policy = SolverController.CaptureSearchPolicy(SolverSettings.Capture(), live,
            includeTurnSetup: false, theftPolicy: SolverController.ResolveTheftPolicy(live));
        policy = policy with { Profile = new SolverSearchProfile(24, 1000, 32, 18, 24, 6000), MaxDegreeOfParallelism = 1 };
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var solver = new CombatBeamSolver(root, names, damage, policy, cancel.Token, searchProfile: policy.Profile);
        var result = solver.Solve();
        double solveMs = watch.Elapsed.TotalMilliseconds;
        var actions = result.BestNode.Actions;
        if (!result.Snapshot.AllEnemiesDead || result.Snapshot.PlayerDead || actions.Count is < 1 or > 48)
            throw new InvalidOperationException($"No bounded win: {result.BoundaryReason} ({actions.Count} actions)");
        var ids = live.Enemies.Select(enemy => enemy.CombatId).ToArray();
        var state = Step(solver, null, null);
        object?[] Capture()
        {
            var engine = (CombatPredictionSimulator)state.Simulator;
            var combat = (SimulatedCombatState)engine.State.CombatState;
            return ids.Select(id => Predicted.Invoke(null, new object[] {
                engine, combat, player, combat.KnownEnemies.Single(e => e.CombatId == id) })).ToArray();
        }
        var initial = Capture();
        var frames = new List<object?[]>();
        try
        {
            foreach (var action in actions)
            {
                if (action.Kind is not (PlanActionKind.PlayCard or PlanActionKind.EndTurn)
                    || action.Choice != null || action.NestedChoices?.Count > 0 || action.TurnStartChoices?.Count > 0)
                    throw new InvalidOperationException("Unsupported plan action or choice");
                var next = Step(solver, state, action);
                state.ReleaseSimulator();
                state = next;
                frames.Add(Capture());
            }
            if (!state.AllEnemiesDead || state.PlayerDead) throw new InvalidOperationException("Prediction replay did not win");
        }
        finally { state.ReleaseSimulator(); }
        return new() { ["type"] = "i1_plan", ["solve_ms"] = solveMs, ["ms"] = watch.Elapsed.TotalMilliseconds,
            ["actions"] = actions.Select(a => new { kind = a.Kind.ToString(), a.Turn, a.CardId,
                a.CardOccurrence, a.CardStateKey, a.CardStateOccurrence, a.TargetCombatId }), ["root"] = initial, ["frames"] = frames };
    }

    private static MethodInfo Private(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.NonPublic)!;
    private static MethodInfo Replay => Private(typeof(CombatBeamSolver), "Replay");
    private static MethodInfo Actual => Private(typeof(UnattendedTestRunner), "CaptureActual");
    private static MethodInfo Predicted => Private(typeof(UnattendedTestRunner), "CaptureSimulated");
    private static Func<object?[]>? _nativeCapture;
    private static object?[]? _terminal;
    private static void ObserveTerminal() => _terminal ??= _nativeCapture?.Invoke();

    private static SimulationSnapshot Step(CombatBeamSolver solver, SimulationSnapshot? parent, PlanAction? action)
    {
        object?[] args = Enumerable.Repeat<object?>(Type.Missing, Replay.GetParameters().Length).ToArray();
        args[0] = action == null ? Array.Empty<PlanAction>() : new[] { action };
        args[1] = parent;
        if (parent != null) args[2] = parent.Turn;
        return (SimulationSnapshot)Replay.Invoke(solver, args)!;
    }
}
