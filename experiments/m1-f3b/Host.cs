using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Combat;
using OfflineSearchHarness;

namespace Sts2Headless;

internal static partial class IntegrationProbe
{
    private static Dictionary<string, object?> RunFirstWin(CombatState live, JsonElement request)
    {
        int cap = request.GetProperty("cap").GetInt32();
        string arm = request.GetProperty("arm").GetString()!;
        if (cap is < 1 or > 2048 || arm is not ("A" or "B" or "C" or "D"))
            throw new ArgumentOutOfRangeException(nameof(request), "Invalid F3B arm or transition cap");

        var clock = Stopwatch.StartNew();
        var root = CombatRootSnapshot.Capture(live);
        var player = live.Players.Single();
        if (Entry.Logger == null)
            typeof(Entry).GetProperty("Logger")!.SetValue(null, new CombatSolverLog(
                Environment.GetEnvironmentVariable("I1_LOG")!));
        var policy = SolverController.CaptureSearchPolicy(SolverSettings.Capture(), live, false, null)
            with { MaxDegreeOfParallelism = 1 };
        var solver = new CombatBeamSolver(root, SolverDisplayNames.Capture(live), BattleDamageTracker.Observe(live), policy);
        var seed = Step(solver, null, null);
        object?[] expected, actual;
        try
        {
            var shadow = (SimulatedCombatState)seed.Simulator.State.CombatState;
            expected = live.Enemies.Select(e => Predicted.Invoke(null, new object?[] {
                seed.Simulator, shadow, player, shadow.KnownEnemies.Single(x => x.CombatId == e.CombatId) })).ToArray();
            actual = live.Enemies.Select(e => Actual.Invoke(null, new object?[] { live, player, e })).ToArray();
        }
        catch
        {
            seed.ReleaseSimulator();
            throw;
        }

        if (JsonSerializer.Serialize(expected) != JsonSerializer.Serialize(actual))
        {
            seed.ReleaseSimulator();
            return new() { ["type"] = "f3b_result", ["status"] = "root_prediction_mismatch",
                ["expected"] = expected, ["actual"] = actual };
        }
        clock.Stop();
        using var search = new FirstWin(player, seed, (parent, action) => Step(solver, parent, action), cap,
            request.GetProperty("potions").GetBoolean(),
            request.GetProperty("rejected").EnumerateArray().Select(x => x.GetString()!).ToHashSet());
        return new() { ["type"] = "f3b_result", ["root_prepare_ms"] = clock.Elapsed.TotalMilliseconds,
            ["search"] = search.Run(arm, request.TryGetProperty("repair_probe", out var probe) ? probe : null) };
    }
}
