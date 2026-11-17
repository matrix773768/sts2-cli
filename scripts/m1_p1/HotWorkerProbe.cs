using System.Diagnostics;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Saves.Validation;

namespace Sts2Headless;

// All timing scopes are confined to the protocol thread. Nested scopes report exclusive time.
internal sealed class ProbeTiming(string name) : IDisposable
{
    private static readonly Dictionary<string, long> Totals = new();
    private static ProbeTiming? _current;
    private readonly ProbeTiming? _parent = _current;
    private readonly long _start = Stopwatch.GetTimestamp();
    private long _children;

    public static int ProtocolThread { private get; set; }

    public static ProbeTiming? Begin(string name) =>
        Environment.CurrentManagedThreadId == ProtocolThread
            ? _current = new ProbeTiming(name)
            : null;

    public static T Measure<T>(string name, Func<T> operation)
    {
        using var phase = Begin(name);
        return operation();
    }

    public void Dispose()
    {
        long elapsed = Stopwatch.GetTimestamp() - _start;
        Totals[name] = Totals.GetValueOrDefault(name) + elapsed - _children;
        if (_parent != null)
            _parent._children += elapsed;
        _current = _parent;
    }

    public static Dictionary<string, double> Take()
    {
        var result = Totals.ToDictionary(pair => pair.Key,
            pair => pair.Value * 1000.0 / Stopwatch.Frequency);
        Totals.Clear();
        return result;
    }
}

public partial class RunSimulator
{
    private static string? _initialProgress;

    internal static string ProbeProgress() =>
        SaveManager.ToJson(SaveManager.Instance.Progress.ToSerializable());

    private void ProbeTurnStarted(CombatState _) => _turnStarted.Set();
    private void ProbeCombatEnded(CombatRoom _) => _combatEnded.Set();

    internal object ProbeRng()
    {
        using var phase = ProbeTiming.Begin("rng_observation");
        var state = _runState ?? throw new InvalidOperationException("No run");
        return new
        {
            Run = state.Rng.ToSerializable(),
            Player = state.Players[0].PlayerRng.ToSerializable(),
        };
    }

    internal void ProbeReset()
    {
        using var cleanup = ProbeTiming.Begin("native_cleanup");
        if (_runState?.CurrentRoom is not MapRoom
            || HasPendingSelection || _pendingBundleTcs != null
            || _pendingEventOptionTask is { IsCompletedSuccessfully: false }
            || _merchantPurchase is { IsCompletedSuccessfully: false }
            || _pendingRewards != null || _pendingCardReward != null
            || _combatTurnTimedOut || CombatManager.Instance.IsInProgress
            || RunManager.Instance.ActionExecutor.IsRunning
            || !_syncCtx.ProbeIdle || YieldPatches.SuppressYield)
            throw new InvalidOperationException("Reset requires an idle, settled map boundary");

        CombatManager.Instance.TurnStarted -= ProbeTurnStarted;
        CombatManager.Instance.CombatEnded -= ProbeCombatEnded;
        _cardSelectorScope?.Dispose();
        _cardSelectorScope = null;
        RunManager.Instance.CleanUp(graceful: true);
        if (RunManager.Instance.IsInProgress || CombatManager.Instance.IsInProgress
            || !_syncCtx.ProbeIdle || YieldPatches.SuppressYield)
            throw new InvalidOperationException("Native cleanup did not quiesce");
        LocPatches._bundleSimRef = null;
        _turnStarted.Dispose();
        _combatEnded.Dispose();
    }

    internal static void ProbeRestoreProgress()
    {
        using var phase = ProbeTiming.Begin("profile_restore");
        var baseline = SaveManager.FromJson<SerializableProgress>(
            _initialProgress ?? throw new InvalidOperationException("Missing initial profile progress"));
        if (!baseline.Success || baseline.SaveData == null)
            throw new InvalidOperationException("Cannot deserialize initial profile progress");
        SaveManager.Instance.Progress = ProgressState.FromSerializable(
            baseline.SaveData, new DeserializationContext());
    }
}

partial class Program
{
    private static Dictionary<string, object?> ProbeBatch(RunSimulator sim, JsonElement actions)
    {
        if (actions.GetArrayLength() is < 1 or > 64)
            throw new InvalidOperationException("Expected 1–64 actions");

        var steps = new List<object>();
        foreach (var action in actions.EnumerateArray())
        {
            if (action.GetProperty("cmd").GetString() != "action")
                throw new InvalidOperationException("Expected action command");
            var state = HandleCommand(sim, action)!;
            if (!state.TryGetValue("decision", out var decision))
                throw new InvalidOperationException($"Action {steps.Count + 1} failed: {state.GetValueOrDefault("message")}");
            steps.Add(new { state, map = sim.GetFullMap(includeStart: true), rng = sim.ProbeRng() });
            if (decision is not "combat_play")
                break;
        }
        return new() { ["type"] = "batch", ["steps"] = steps };
    }
}
