using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

internal sealed class RouteProbe : IDisposable
{
    internal sealed record Move(int HandIndex, string Id, uint? Target);
    internal sealed record Pick(string Id, string Key, int Upgrade, int OptionOccurrence);
    internal sealed record Input(int Turn, Move? Selected, Pick? Pick);
    private static readonly JsonSerializerOptions Json = UnattendedTestFiles.JsonOptions;
    private static readonly MethodInfo Replay = AccessTools("Replay", typeof(CombatBeamSolver));
    private static readonly MethodInfo Actual = AccessTools("CaptureActual", typeof(UnattendedTestRunner));
    private static readonly MethodInfo Predicted = AccessTools("CaptureSimulated", typeof(UnattendedTestRunner));
    private static MethodInfo AccessTools(string method, Type type)
        => type.GetMethod(method, BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)!;
    private readonly CombatState _combat;
    private readonly Player _player;
    private readonly MegaCrit.Sts2.Core.Entities.Creatures.Creature[] _enemies;
    private readonly CombatBeamSolver _solver;
    private readonly CombatRootSnapshot _root;
    private SimulationSnapshot _state;
    private JsonNode? _nativeTerminal;
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private readonly long _allocated = GC.GetTotalAllocatedBytes(false);
    private readonly string _output;
    private readonly List<PlanAction> _plan = [];
    private readonly List<object> _steps = [];
    private int _matched;
    private string? _digest;
    private double _compareMs;
    private string _status = "matching";
    private object? _difference;
    private readonly double _captureMs, _initializeMs, _rootForkMs;
    internal Input[] Inputs { get; }

    internal RouteProbe(CombatState combat, string output)
    {
        _combat = combat;
        _output = output;
        _player = combat.Players.Single();
        _enemies = combat.Enemies.ToArray();
        Inputs = JsonSerializer.Deserialize<Input[]>(File.ReadAllText(
            Environment.GetEnvironmentVariable("M1E1_INPUT")!), Json)!;
        if (Inputs.Length is < 1 or > 64) throw new InvalidOperationException("Fixed route length out of bounds");
        long start = Stopwatch.GetTimestamp();
        _root = CombatRootSnapshot.Capture(combat);
        _captureMs = Elapsed(start);
        start = Stopwatch.GetTimestamp();
        var policy = SolverController.CaptureSearchPolicy(SolverSettings.Capture(), combat, false, null);
        _solver = new(_root, SolverDisplayNames.Capture(combat), BattleDamageTracker.Observe(combat), policy);
        _initializeMs = Elapsed(start);
        start = Stopwatch.GetTimestamp();
        _state = Step(_solver, null, null);
        _rootForkMs = Elapsed(start);
        Compare(0);
    }

    internal bool Ready => _status == "matching";
    internal void CaptureTerminal() => _nativeTerminal = Native();

    private JsonNode Native() => JsonSerializer.SerializeToNode(
        _enemies.Select(e => Actual.Invoke(null, [_combat, _player, e])).ToArray(), Json)!;
    private JsonNode Shadow(SimulationSnapshot snapshot)
        => JsonSerializer.SerializeToNode(_enemies.Select(e => Predicted.Invoke(null, [snapshot.Simulator,
            (SimulatedCombatState)snapshot.Simulator.State.CombatState, _player, e])).ToArray(), Json)!;

    internal bool Predict(int index)
    {
        var input = Inputs[index];
        var pcs = _player.PlayerCombatState!;
        if (pcs.TurnNumber != input.Turn) throw new InvalidOperationException("Fixed turn mismatch");
        PlanAction action;
        if (input.Selected == null)
            action = new(PlanActionKind.EndTurn, input.Turn);
        else
        {
            var card = pcs.Hand.Cards[input.Selected.HandIndex];
            if (card.Id.Entry != input.Selected.Id) throw new InvalidOperationException("Fixed card mismatch");
            var preceding = pcs.Hand.Cards.Take(input.Selected.HandIndex);
            var key = CardChoiceSupport.ChoiceCardKey(card);
            PlanCardChoice? choice = null;
            if (input.Pick is { } pick)
            {
                if (card.Id.Entry != "BURNING_PACT") throw new InvalidOperationException("Unmapped choice");
                var token = new PlanCardToken(pick.Id, pick.Upgrade, pick.Key, pick.OptionOccurrence, pick.OptionOccurrence, "");
                choice = new(PlanChoiceEffect.Exhaust, PileType.Hand, [token]);
            }
            action = new(PlanActionKind.PlayCard, input.Turn, CardId: card.Id.Entry,
                CardOccurrence: preceding.Count(c => c.Id.Entry == card.Id.Entry),
                TargetCombatId: input.Selected.Target, Choice: choice, CardStateKey: key,
                CardStateOccurrence: preceding.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key));
        }
        var start = Stopwatch.GetTimestamp();
        var next = Step(_solver, _state, action);
        var ms = Elapsed(start);
        _state.ReleaseSimulator();
        _state = next;
        _plan.Add(action);
        if (next.HasRisk || next.BoundaryReason != SearchBoundaryReason.None)
        {
            _status = "prediction_boundary";
            _difference = new { step = index + 1, action, next.HasRisk, next.BoundaryReason, next.PredictionGaps };
            return false;
        }
        _steps.Add(new { index = index + 1, action.CardId, action.Kind, predictionMs = ms });
        return true;
    }

    internal bool Compare(int index)
    {
        long start = Stopwatch.GetTimestamp();
        Compare(index, _nativeTerminal ?? Native());
        _compareMs += Elapsed(start);
        return Ready;
    }

    private void Compare(int index, JsonNode actual)
    {
        var predicted = Shadow(_state);
        if (JsonNode.DeepEquals(predicted, actual))
        {
            _matched = index;
            _digest = Digest(predicted);
            return;
        }
        var differences = new List<object>();
        for (int i = 0; i < _enemies.Length; i++)
        {
            var p = predicted[i]!.AsObject();
            var a = actual[i]!.AsObject();
            foreach (var field in p)
                if (!JsonNode.DeepEquals(field.Value, a[field.Key]))
                    differences.Add(new { enemy = i, field = field.Key, predicted = field.Value, actual = a[field.Key] });
        }
        _status = "state_difference";
        _difference = new { step = index, differences };
    }

    internal void Finish(string nativeStatus)
    {
        bool complete = Ready && _plan.Count == Inputs.Length &&
            ((nativeStatus == "win" && _state.AllEnemiesDead && !_state.PlayerDead)
                || (nativeStatus == "death" && _state.PlayerDead));
        double auditedMs = _clock.Elapsed.TotalMilliseconds;
        var benchmark = _matched > 0 ? Benchmark() : null;
        File.WriteAllText(Path.Combine(_output, "audit.json"), JsonSerializer.Serialize(new
        {
            status = complete ? "pass" : Ready ? "native_incomplete" : _status,
            nativeStatus, planned = Inputs.Length, steps = _steps, _difference,
            rootCaptureMs = _captureMs, solverAdapterMs = _initializeMs, rootForkAndSnapshotMs = _rootForkMs,
            auditedMs, compareMs = _compareMs, matched = _matched, benchmark,
            allocatedBytes = GC.GetTotalAllocatedBytes(false) - _allocated,
            peakWorkingSetBytes = Process.GetCurrentProcess().PeakWorkingSet64,
        }, Json));
        if (complete)
            File.WriteAllText(Path.Combine(_output, "verified-plan.json"), JsonSerializer.Serialize(_plan, Json));
    }

    private object Benchmark()
    {
        var samples = new List<object>();
        for (int repeat = 0; repeat < 7; repeat++)
        {
            long bytes = GC.GetAllocatedBytesForCurrentThread();
            long start = Stopwatch.GetTimestamp();
            var state = Step(_solver, null, null);
            double forkMs = Elapsed(start);
            long advanceStart = Stopwatch.GetTimestamp();
            try
            {
                foreach (var action in _plan.Take(_matched))
                {
                    var next = Step(_solver, state, action);
                    state.ReleaseSimulator();
                    state = next;
                }
                double advanceMs = Elapsed(advanceStart);
                long allocatedBytes = GC.GetAllocatedBytesForCurrentThread() - bytes;
                if (Digest(Shadow(state)) != _digest)
                    throw new InvalidOperationException("Unaudited benchmark result");
                samples.Add(new { forkMs, advanceMs, allocatedBytes });
            }
            finally { state.ReleaseSimulator(); }
        }
        return new { samples, branch = Branch() };
    }

    private object? Branch()
    {
        int index = _plan.FindIndex(action => action.CardId == "FRANTIC_ESCAPE");
        if (index < 0 || index >= _matched)
            return null;
        var parent = Step(_solver, null, null);
        try
        {
            foreach (var action in _plan.Take(index))
            {
                var next = Step(_solver, parent, action);
                parent.ReleaseSimulator();
                parent = next;
            }

            string before = Digest(Shadow(parent));
            var first = BranchStep(parent, _plan[index]);
            var alternative = BranchStep(parent, new PlanAction(PlanActionKind.EndTurn, parent.Turn));
            var repeated = BranchStep(parent, _plan[index]);
            bool parentUnchanged = before == Digest(Shadow(parent));
            bool repeatEqual = first.Digest == repeated.Digest;
            bool distinct = first.Digest != alternative.Digest;
            return new { prefix = index, parentUnchanged, repeatEqual, distinct, first, alternative, repeated };
        }
        finally { parent.ReleaseSimulator(); }
    }

    private sealed record Child(string Digest, double Ms, string Boundary, bool Risk);

    private Child BranchStep(SimulationSnapshot parent, PlanAction action)
    {
        long start = Stopwatch.GetTimestamp();
        var child = Step(_solver, parent, action);
        double ms = Elapsed(start);
        try { return new(Digest(Shadow(child)), ms, child.BoundaryReason.ToString(), child.HasRisk); }
        finally { child.ReleaseSimulator(); }
    }

    private static string Digest(JsonNode state)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(state.ToJsonString(Json))));

    private static SimulationSnapshot Step(CombatBeamSolver solver, SimulationSnapshot? parent, PlanAction? action)
    {
        var args = Enumerable.Repeat<object?>(Type.Missing, Replay.GetParameters().Length).ToArray();
        args[0] = action == null ? Array.Empty<PlanAction>() : new[] { action };
        args[1] = parent;
        if (parent != null) args[2] = parent.Turn;
        args[13] = false;
        return (SimulationSnapshot)Replay.Invoke(solver, args)!;
    }

    private static double Elapsed(long start) => Stopwatch.GetElapsedTime(start).TotalMilliseconds;
    public void Dispose() => _state.ReleaseSimulator();
}
