using System.Diagnostics;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Text.Json;
using CombatSolver;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;

namespace OfflineSearchHarness;

internal static class NativeWitness
{
    private static Func<object>? _capture;
    private static object? _terminal;
    private static int _alive;
    private static int _hp;

    internal static void Run(CombatState combat, MainLoopContext loop, string source, string output)
    {
        using var expected = JsonDocument.Parse(File.ReadAllText(Path.Combine(source, "harness-result.json")));
        var search = expected.RootElement.GetProperty("search");
        var root = CombatRootSnapshot.Capture(combat);
        if (root.LiveStamp.StateText != search.GetProperty("rootLiveStamp").GetString()
            || root.ContinuationStamp.StateText != search.GetProperty("rootContinuationStamp").GetString())
            throw new InvalidOperationException("Native replay root or RNG differs");
        PlanAction[] actions = JsonSerializer.Deserialize<PlanAction[]>(
            File.ReadAllText(Path.Combine(source, "route.json")), UnattendedTestFiles.JsonOptions)!;
        var player = combat.Players.Single();
        var manager = CombatManager.Instance;
        var executor = RunManager.Instance.ActionExecutor;
        var patch = new Harmony("m1-h1.native-witness");
        var end = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
            .Single(m => m.Name == "EndCombatInternal" && m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
        var wrapper = AccessTools.Method(typeof(CardModel), "OnPlayWrapper");
        var moveNext = AccessTools.Method(wrapper.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType, "MoveNext");
        patch.Patch(end, prefix: Hook(nameof(CaptureTerminal)));
        patch.Patch(moveNext, transpiler: Hook(nameof(Timer)));
        patch.Patch(AccessTools.Method(typeof(RunManager), "WriteReplay", [typeof(bool)]), prefix: Hook(nameof(Skip)));
        patch.Patch(AccessTools.Method(AccessTools.TypeByName("NHoverTipSet"), "Clear", []), prefix: Hook(nameof(Skip)));

        var history = new List<object>();
        var watch = Stopwatch.StartNew();
        var pcs = player.PlayerCombatState!;
        _capture = () => new { hp = _hp = player.Creature.CurrentHp, aliveEnemies = _alive = combat.Enemies.Count(e => e.CurrentHp > 0), turn = pcs.TurnNumber };
        foreach (var action in actions)
        {
            if (!manager.IsInProgress || pcs.TurnNumber != action.Turn || action.Choice != null
                || action.NestedChoices?.Count > 0 || action.TurnStartChoices?.Count > 0)
                throw new InvalidOperationException($"Unsupported replay at action {history.Count + 1}: {action}");
            if (action.Kind == PlanActionKind.EndTurn)
            {
                manager.OnEndedTurnLocally();
                RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new EndPlayerTurnAction(player, action.Turn));
            }
            else if (action.Kind == PlanActionKind.PlayCard)
            {
                var card = pcs.Hand.Cards.Where(c => c.Id.Entry == action.CardId
                    && CardChoiceSupport.ChoiceCardKey(c) == action.CardStateKey).ElementAt(action.CardStateOccurrence);
                var target = action.TargetCombatId is uint id ? combat.Enemies.Single(e => e.CombatId == id) : null;
                if (!card.CanPlayTargeting(target) || !card.TryManualPlay(target))
                    throw new InvalidOperationException($"Native rejected {action.CardId}");
            }
            else
                throw new InvalidOperationException($"Unsupported action {action.Kind}");
            loop.RunUntilCompleted(executor.FinishedExecutingActions(), TimeSpan.FromSeconds(4), "native action");
            while (action.Kind == PlanActionKind.EndTurn && _terminal == null
                && (pcs.TurnNumber <= action.Turn || pcs.Phase != PlayerTurnPhase.Play))
            {
                if (watch.Elapsed.TotalSeconds > 24) throw new TimeoutException("Native turn deadline");
                loop.Pump(TimeSpan.FromMilliseconds(10));
            }
            history.Add(new { action.Turn, kind = action.Kind.ToString(), action.CardId, action.TargetCombatId, state = _terminal ?? _capture() });
        }
        if (_terminal == null || manager.IsInProgress || _hp <= 0 || _alive != 0)
            throw new InvalidOperationException("Native victory settlement absent");
        File.WriteAllText(Path.Combine(output, "native.json"), JsonSerializer.Serialize(new
        {
            scope = "offline-teacher", rootAndRngMatched = true, actions = history, terminal = _terminal,
            postCombatHp = player.Creature.CurrentHp, combatInProgress = manager.IsInProgress,
        }, UnattendedTestFiles.JsonOptions));
    }

    private static HarmonyMethod Hook(string name) => new(AccessTools.Method(typeof(NativeWitness), name));
    private static void CaptureTerminal() => _terminal ??= _capture?.Invoke();
    private static bool Skip() => false;
    private static ulong Ticks() => (ulong)Environment.TickCount64;

    private static IEnumerable<CodeInstruction> Timer(IEnumerable<CodeInstruction> instructions)
    {
        foreach (var item in instructions)
        {
            if (item.operand is MethodInfo method && method.DeclaringType?.FullName == "Godot.Time"
                && method.Name == "GetTicksMsec")
            {
                item.opcode = OpCodes.Call;
                item.operand = AccessTools.Method(typeof(NativeWitness), nameof(Ticks));
            }
            yield return item;
        }
    }
}
