using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using CombatSolver;
using MegaCrit.Sts2.Core.Combat;

namespace Sts2Headless;

internal static partial class IntegrationProbe
{
    private static Dictionary<string, object?> ProbePredictionBoundary(JsonElement request, string command)
    {
        var live = CombatManager.Instance.DebugOnlyGetState();
        var result = new Dictionary<string, object?> {
            ["type"] = "p2_boundary", ["live_combat"] = live is not null,
            ["native_in_progress"] = CombatManager.Instance.IsInProgress
        };
        if (command == "i1_p2_import")
        {
            var text = request.GetProperty("continuation").GetString()!;
            var restored = JsonSerializer.Deserialize<ContinuationStamp>(JsonSerializer.Serialize(new ContinuationStamp(text)))!;
            result["stamp_roundtrip"] = restored.StateText == text;
            result["root_import_error"] = JsonFailure(() =>
                JsonSerializer.Deserialize<CombatRootSnapshot>(request.GetProperty("root_metadata").GetRawText()));
            return result;
        }

        if (live is null)
            throw new InvalidOperationException("P2 export requires an active source");
        var clock = Stopwatch.StartNew();
        var root = CombatRootSnapshot.Capture(live);
        result["capture_ms"] = clock.Elapsed.TotalMilliseconds;
        clock.Restart();
        var first = root.ForkSimulator();
        var second = root.ForkSimulator();
        result["two_forks_ms"] = clock.Elapsed.TotalMilliseconds;
        var player = live.Players.Single();
        var predicted = ContinuationStamp.CapturePredicted(player, first, root.StartTurnNumber,
            root.Forecast, root.StartTurnNumber);
        result["matches_projection"] = predicted == root.ContinuationStamp;
        result["live_unchanged"] = ContinuationStamp.CaptureLive(live) == root.ContinuationStamp;
        result["player_is_live_reference"] = ReferenceEquals(player, root.PlayerIdentity);
        result["enemy_is_live_reference"] = ReferenceEquals(live.Enemies[0], root.Enemies[0]);
        result["fork_player_state_isolated"] = !ReferenceEquals(first.State.GetPlayerCombatState(player),
            second.State.GetPlayerCombatState(player));
        result["fork_rng_isolated"] = !ReferenceEquals(first.Rng, second.Rng);
        result["root_public_constructors"] = typeof(CombatRootSnapshot).GetConstructors().Length;
        result["root_retains_private_simulator"] = typeof(CombatRootSnapshot)
            .GetField("_rootSimulator", BindingFlags.NonPublic | BindingFlags.Instance)?.GetValue(root) is not null;
        try
        {
            result["root_json"] = JsonSerializer.SerializeToElement(root);
            result["root_export_error"] = null;
        }
        catch (Exception error) when (error is JsonException or NotSupportedException or InvalidOperationException)
        {
            result["root_export_error"] = $"{error.GetType().Name}: {error.Message}";
        }
        result["continuation"] = root.ContinuationStamp.StateText;
        result["root_metadata"] = new { root.StartTurnNumber, root.TotalFloor, root.InitialPlayerHp,
            root.InitialPlayerMaxHp, root.ContinuationStamp };
        return result;
    }

    private static string? JsonFailure(Action operation)
    {
        try
        {
            operation();
            return null;
        }
        catch (Exception error) when (error is JsonException or NotSupportedException)
        {
            return error.Message;
        }
    }
}
