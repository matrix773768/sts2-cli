using System.Diagnostics;
using System.Text.Json;
using CombatSolver;

namespace OfflineSearchHarness;

internal static class CandidateProbe
{
    internal static void Run(CombatRootSnapshot root, SolverDisplayNames names,
        BattleDamageSnapshot damage, SearchPolicySnapshot policy, MainLoopContext loop, string output)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(4));
        var task = Task.Run(() =>
        {
            var generated = new List<SearchPathObservation>();
            var retention = new List<SearchPathObservation>();
            var observer = new SearchPathObserver(_ => true, item =>
            {
                if (item.ActionCount != 1)
                    return;
                if (item.Stage == SearchPathObservationStage.Generated)
                    generated.Add(item);
                if (item.Stage == SearchPathObservationStage.GlobalRetention)
                    retention.Add(item);
            }, _ => true);
            var discovery = policy with
            {
                Profile = policy.Profile with { MaxExpandedNodes = 24 },
                Diagnostics = new SearchDiagnosticsSink(_ => { }, _ => { }, observer),
            };
            new CombatBeamSolver(root, names, damage, discovery, deadline.Token,
                searchProfile: discovery.Profile).Solve();

            var json = UnattendedTestFiles.JsonOptions;
            static PlanAction Normalize(PlanAction action) => action with
            { RelicEffects = null, CardTitle = "", TargetName = "", PotionTitle = "" };
            string Key(PlanAction action) => JsonSerializer.Serialize(Normalize(action), json);
            var rows = new List<object>();
            foreach (var group in generated.Where(item => item.Actions.Count == 1)
                .GroupBy(item => Key(item.Actions[0])))
            {
                var candidate = group.First();
                var action = candidate.Actions[0];
                var pool = retention.Where(item => item.Actions.Count == 1
                    && item.StateKey == candidate.StateKey && Key(item.Actions[0]) == group.Key)
                    .Select(item => new { item.BoundaryId, item.Reason, item.Retention }).ToArray();
                var replay = new CombatBeamSolver(root, names, damage, policy, deadline.Token,
                    searchProfile: policy.Profile);
                var immediate = replay.ReplayDiagnosticPrefix([action]);
                int energy = immediate.Energy, block = immediate.PlayerBlock;
                bool replayMatched = immediate.StateKey == candidate.StateKey;
                immediate.ReleaseSimulator();
                var watch = Stopwatch.StartNew();
                SolverResult? result = null;
                string? failure = null;
                try
                {
                    result = new CombatBeamSolver(root, names, damage, policy, deadline.Token,
                        searchProfile: policy.Profile, fixedPrefixActions: [action]).Solve();
                }
                catch (PotionPolicyUnsatisfiedException)
                {
                    failure = "PotionPolicyUnsatisfied";
                }
                watch.Stop();
                bool matched = result != null && result.BestNode.Actions.Count > 0 && Key(result.BestNode.Actions[0]) == group.Key;
                var quality = result == null ? null : CombatSearchCoordinator.CapturePortfolioQuality(root, policy, result);
                var outcome = !matched ? "unknown"
                    : quality!.Won ? "win"
                    : result!.Snapshot.PlayerDead ? "death"
                    : result.BoundaryReason != SearchBoundaryReason.None ? "truncated" : "unknown";
                rows.Add(new
                {
                    action, candidate.ParentStateKey, candidate.StateKey, candidate.ActionCount,
                    candidate.Score, candidate.PlayerHp, candidate.EnemyHp, candidate.CumulativePlayerHpLost,
                    candidate.Traits, candidate.ShufflesCrossed, candidate.HasPredictionRisk,
                    energy, block, replayMatched, pool, outcome, matched, quality, failure,
                    boundaryReason = result?.BoundaryReason, risk = result?.Snapshot.HasRisk,
                    endShuffles = result?.Snapshot.ShufflesCrossed,
                    expandedNodes = result?.ExpandedNodes, transitionCount = result?.TransitionCount, milliseconds = watch.Elapsed.TotalMilliseconds,
                });
            }
            if (rows.Count == 0)
                throw new InvalidOperationException("No first-action transitions observed.");
            File.WriteAllText(Path.Combine(output, "candidates.json"), JsonSerializer.Serialize(new
            {
                scope = "offline-teacher", discoveryNodes = 24,
                budget = ModRuntime.DescribePolicy(policy),
                peakWorkingSet = System.Diagnostics.Process.GetCurrentProcess().PeakWorkingSet64,
                generatedEvents = generated.Count, rows,
            }, json));
        }, deadline.Token);
        loop.RunUntilCompleted(task, TimeSpan.FromMinutes(5), "M1-L1 candidate probe");
        task.GetAwaiter().GetResult();
    }
}
