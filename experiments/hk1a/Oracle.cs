using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotKernel;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rooms;

namespace OfflineSearchHarness;

internal static class Hk1Oracle
{
    private sealed record Resources(int Hp, int MaxHp, int Gold, string?[] Potions, string[] Relics);
    private static Action? captureTerminal;
    private static void BeforeEndCombat() => captureTerminal?.Invoke();

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
        Resources Snapshot() => new(player.Creature.CurrentHp, player.Creature.MaxHp, player.Gold,
            player.PotionSlots.Select(p => p?.Id.Entry).ToArray(),
            player.Relics.Select(r => r.Id.Entry).ToArray());
        var initial = Snapshot();
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
        else if (mode is "replay" or "hp-fixture")
        {
            var route = mode == "hp-fixture" ? null
                : JsonSerializer.Deserialize<Route>(File.ReadAllText(args[4]), Json)!;
            if (mode == "hp-fixture")
            {
                var enemy = combat.Enemies.Single();
                enemy.SetCurrentHpInternal(8);
                route = new(root, [new(PlanActionKind.PlayCard, 1, CardId: "FEED",
                    TargetCombatId: enemy.CombatId)], [], initial.Hp + 3, initial.MaxHp + 3);
            }
            ArgumentNullException.ThrowIfNull(route);
            if (root != route.Root)
                throw new InvalidOperationException("Cold native root differs from the search root");
            if (route.Actions.Length is 0 or > 2048)
                throw new InvalidOperationException("Route exceeds the 2048-action safety limit or is empty");
            var watch = Stopwatch.StartNew();
            var frames = new List<string>();
            var diagnostics = new List<object>();
            var outcome = HotCombatOutcome.Ongoing;
            Resources? locked = null, callback = null;
            void OnEnd(CombatRoom _) => callback = Snapshot();
            var end = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
                .Single(m => m.Name == "EndCombatInternal" &&
                    m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
            var harmony = new Harmony("hk1a.native-terminal");
            captureTerminal = () => locked ??= Snapshot();
            harmony.Patch(end, prefix: new HarmonyMethod(
                AccessTools.Method(typeof(Hk1Oracle), nameof(BeforeEndCombat))));
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
                            diagnostics.Add(new { action.Turn, step = frames.Count, actual = frame,
                                expected = route.Turns.Where(t => t.Turn == action.Turn).Select(t => t.State) });
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
                captureTerminal = null;
                harmony.Unpatch(end, HarmonyPatchType.Prefix, harmony.Id);
            }
            var post = Snapshot();
            result = new { identity, init, frames, diagnostics, initial, locked, callback, post,
                lockedHp = locked?.Hp, hp = post.Hp, maxHp = locked?.MaxHp,
                prediction = new { route.LockedHp, route.MaxHp,
                    hpMatches = locked?.Hp == route.LockedHp, maxHpMatches = locked?.MaxHp == route.MaxHp },
                replayMs = watch.Elapsed.TotalMilliseconds,
                status = outcome == HotCombatOutcome.Victory && locked is { Hp: > 0 } && callback != null
                    ? "native_win" : "terminal_mismatch" };
        }
        else
            throw new ArgumentException("Unknown HK1A operation");
        File.WriteAllText(output, JsonSerializer.Serialize(result, Json));
        return 0;
    }
}
