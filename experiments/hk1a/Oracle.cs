using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rooms;

namespace OfflineSearchHarness;

internal static class Hk1Oracle
{
    private static readonly JsonSerializerOptions Json = new() { IncludeFields = true };
    private sealed record TurnStamp(int Turn, string State);
    private sealed record Route(string Root, PlanAction[] Actions, TurnStamp[] Turns,
        int LockedHp, int MaxHp);

    public static int Run(string[] args)
    {
        string mode = args[0], input = args[1], output = args[2];
        var clock = Stopwatch.StartNew();
        var loop = new MainLoopContext();
        var options = new HarnessOptions
        {
            OutputDirectory = Path.GetDirectoryName(output)!,
            WorkspaceDirectory = Path.GetDirectoryName(output)!,
            Profile = "Custom", Beam = 96, Nodes = 150000,
            BudgetMilliseconds = int.Parse(args[3]), MaxDegreeOfParallelism = 1,
            PotionPolicy = "Disabled", SearchMode = "Coordinator",
        };
        GameBootstrap.EnsureBootstrapped(loop, options);
        var request = JsonDocument.Parse(File.ReadAllBytes(input));
        var combat = Hk1Root.Open(loop, request.RootElement);
        var player = LocalContext.GetMe(combat)!;
        var identity = Hk1Root.Identity(combat);
        string root = ContinuationStamp.CaptureLive(combat).StateText;
        double init = clock.Elapsed.TotalMilliseconds;
        object result;
        if (mode == "solve")
        {
            var found = ModRuntime.RunSearchDetailed(combat, options, loop, null);
            var snapshot = found.Result.Snapshot;
            Route? route = snapshot.AllEnemiesDead && !snapshot.PlayerDead
                ? new(root, found.Result.BestNode.Actions.ToArray(),
                    found.Result.Continuations.Select(t => new TurnStamp(t.StartTurnNumber, t.ExpectedState.StateText)).ToArray(),
                    snapshot.PlayerHp, snapshot.PlayerMaxHp)
                : null;
            result = new { identity, init, route, search = found.LegacyMetrics, found.WallSeconds,
                boundary = found.Result.BoundaryReason.ToString() };
        }
        else if (mode == "replay")
        {
            var route = JsonSerializer.Deserialize<Route>(File.ReadAllText(args[4]), Json)!;
            if (root != route.Root)
                throw new InvalidOperationException("Cold native root differs from the search root");
            if (route.Actions.Length is 0 or > 2048)
                throw new InvalidOperationException("Route exceeds the 2048-action safety limit or is empty");
            var watch = Stopwatch.StartNew();
            var frames = new List<string>();
            var outcome = HotCombatOutcome.Ongoing;
            int? lockedHp = null;
            void OnEnd(CombatRoom _) => lockedHp = player.Creature.CurrentHp;
            CombatManager.Instance.CombatEnded += OnEnd;
            try
            {
                int checkedTurn = player.PlayerCombatState!.TurnNumber;
                foreach (var action in route.Actions)
                {
                    if (outcome != HotCombatOutcome.Ongoing || action.Turn != player.PlayerCombatState!.TurnNumber)
                        throw new InvalidOperationException($"Invalid route position {frames.Count}");
                    if (action.Turn != checkedTurn)
                    {
                        string frame = ContinuationStamp.CaptureLive(combat).StateText;
                        if (!route.Turns.Any(t => t.Turn == action.Turn && t.State == frame))
                            throw new InvalidOperationException($"Continuation differs at turn {action.Turn}");
                        checkedTurn = action.Turn;
                    }
                    var target = combat.GetCreature(action.TargetCombatId);
                    RealCombatAction native;
                    if (action.Kind == PlanActionKind.EndTurn)
                        native = RealCombatAction.EndTurn();
                    else if (action.Kind == PlanActionKind.PlayCard)
                    {
                        var card = SolverController.FindCardForDeployment(player.PlayerCombatState.Hand.Cards.ToList(), action);
                        if (!card.CanPlayTargeting(target))
                            throw new InvalidOperationException($"Illegal card at step {frames.Count}");
                        native = RealCombatAction.PlayCard(card, target);
                    }
                    else
                        throw new InvalidOperationException($"Unexpected action {action.Kind}");
                    var choices = action.GetActionChoicesInExecutionOrder().Concat(action.TurnStartChoices ?? []).ToArray();
                    var selector = new PlanDrivenCardSelector(choices);
                    using (RunManager.Instance.CardSelectorStack.PushSelector(player, selector))
                        outcome = RealCombatDriver.RunRealCombatAction(loop, combat, native,
                            timeout: TimeSpan.FromSeconds(10), externalErrorProbe: () => selector.LastError);
                    frames.Add(outcome == HotCombatOutcome.Ongoing
                        ? OfflineCombat.DescribeRoot(combat) : outcome.ToString());
                }
            }
            finally
            {
                CombatManager.Instance.CombatEnded -= OnEnd;
            }
            int hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp;
            result = new { identity, init, frames, lockedHp, hp, maxHp, player.Gold,
                potions = player.PotionSlots.Select(p => p?.Id.Entry).ToArray(),
                relics = player.Relics.Select(r => r.Id.Entry).ToArray(),
                replayMs = watch.Elapsed.TotalMilliseconds,
                status = outcome == HotCombatOutcome.Victory && lockedHp == route.LockedHp && maxHp == route.MaxHp
                    ? "native_win" : "terminal_mismatch" };
        }
        else
            throw new ArgumentException("Unknown HK1A operation");
        File.WriteAllText(output, JsonSerializer.Serialize(result, Json));
        return 0;
    }
}
