using CombatSolver;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using System.Runtime.Loader;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using CombatSolver.Engine.InCombat.Simulation;
using HarmonyLib;
using MegaCrit.Sts2.Core.Entities.Actions;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2Headless;

internal static class IntegrationProbe
{
    internal static Dictionary<string, object?> Run(RunSimulator sim, JsonElement cmd)
    {
        if (!_loaded) Load();
        var response = Dispatch(sim, cmd);
        using var process = Process.GetCurrentProcess();
        response["mode"] = "offline-teacher";
        response["schema_version"] = 1;
        response["peak_working_set_bytes"] = process.PeakWorkingSet64;
        return response;
    }

    private const string SupportedPotion = "BEETLE_JUICE";
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
        string? command = cmd.GetProperty("cmd").GetString();
        if (command == "i1_release")
        {
            _nativeCapture = null;
            _terminal = null;
            _boundCombat = null;
            BattleDamageTracker.Reset();
            return new() { ["type"] = "i1_released" };
        }
        var live = CombatManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("No live combat");
        var player = live.Players.Single();
        if (!CombatManager.Instance.IsInProgress || player.PlayerCombatState?.Phase !=
            MegaCrit.Sts2.Core.Combat.PlayerTurnPhase.Play)
            throw new InvalidOperationException("Expected a native player action boundary");
        if (_boundCombat != null && !ReferenceEquals(live, _boundCombat))
            throw new InvalidOperationException("Previous combat session was not released");
        switch (command)
        {
            case "i1_begin":
                if (_nativeCapture != null) throw new InvalidOperationException("Replay already started");
                var enemies = live.Enemies.ToArray();
                _boundCombat = live;
                _nativeCapture = () => enemies.Select(enemy =>
                    Actual.Invoke(null, new object[] { live, player, enemy })).ToArray();
                if (!_patched)
                {
                    var method = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
                        .Single(m => m.Name == "EndCombatInternal" && m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
                    new Harmony("m1-i1.capture-terminal").Patch(method,
                        prefix: new HarmonyMethod(Private(typeof(IntegrationProbe), nameof(ObserveTerminal))));
                    _patched = true;
                }
                return new() { ["type"] = "i1_state", ["state"] = _nativeCapture() };
            case "i1_step":
                if (_nativeCapture == null || _terminal != null) throw new InvalidOperationException("Not in replay");
                var action = cmd.GetProperty("action");
                if (player.PlayerCombatState!.TurnNumber != action.GetProperty("turn").GetInt32())
                    return Rejected("Turn differs");
                var args = new Dictionary<string, object?>();
                string kind = action.GetProperty("kind").GetString()!;
                if (kind == "PlayCard")
                {
                    string id = action.GetProperty("card_id").GetString()!;
                    var hand = player.PlayerCombatState.Hand.Cards;
                    string key = action.GetProperty("card_state_key").GetString()!;
                    var matching = Enumerable.Range(0, hand.Count).Where(i => hand[i].Id.Entry == id);
                    int occurrence = action.GetProperty(key.Length == 0 ? "card_occurrence" : "card_state_occurrence").GetInt32();
                    if (occurrence < 0) return Rejected("Invalid card occurrence");
                    if (key.Length != 0)
                        matching = matching.Where(i => CardChoiceSupport.ChoiceCardKey(hand[i]) == key);
                    var cardIndex = matching.Skip(occurrence).FirstOrDefault(-1);
                    if (cardIndex < 0) return Rejected("Card instance missing");
                    var card = hand[cardIndex];
                    args["card_index"] = cardIndex;
                    MegaCrit.Sts2.Core.Entities.Creatures.Creature? target = null;
                    if (action.TryGetProperty("target_combat_id", out var targetId))
                    {
                        var alive = live.Enemies.Where(e => e.IsAlive).ToList();
                        var targetIndex = alive.FindIndex(e => e.CombatId == targetId.GetUInt32());
                        if (targetIndex < 0) return Rejected("Missing target");
                        args["target_index"] = targetIndex;
                        target = alive[targetIndex];
                    }
                    if ((card.TargetType == TargetType.AnyEnemy) != (target != null))
                        return Rejected("Target does not match Headless action contract");
                    if (!card.CanPlayTargeting(target)) return Rejected("Illegal card or target");
                }
                else if (kind is not ("EndTurn" or "UsePotion")) return Rejected("Unsupported action");

                string nativeAction;
                Dictionary<string, object?> decision;
                if (kind == "UsePotion")
                {
                    if (action.GetProperty("potion_id").GetString() != SupportedPotion ||
                        HasChoice(action, "choice") || HasChoice(action, "nested_choices") ||
                        HasChoice(action, "turn_start_choices"))
                        return Rejected("Unsupported potion shape");
                    int slot = action.GetProperty("potion_slot").GetInt32();
                    if (slot < 0 || slot >= player.PotionSlots.Count ||
                        player.PotionSlots[slot] is not { } potion || potion.Id.Entry != SupportedPotion)
                        return Rejected("Invalid potion slot or ID");
                    if (potion.TargetType != TargetType.AnyEnemy ||
                        !action.TryGetProperty("target_combat_id", out var potionTarget) ||
                        !potionTarget.TryGetUInt32(out uint potionTargetId))
                        return Rejected("Potion requires a target Combat ID");
                    var potionEnemies = live.Enemies.Where(enemy => enemy.IsAlive).ToList();
                    int targetIndex = potionEnemies.FindIndex(enemy => enemy.CombatId == potionTargetId && enemy.IsHittable);
                    if (targetIndex < 0) return Rejected("Invalid potion target");
                    nativeAction = "use_potion";
                    args["potion_slot"] = slot;
                    args["target_index"] = targetIndex;
                    decision = sim.UseTeacherPotion(player, potion, slot, potionEnemies[targetIndex]);
                }
                else
                {
                    nativeAction = kind == "EndTurn" ? "end_turn" : "play_card";
                    decision = sim.ExecuteAction(nativeAction, args);
                }
                if (decision.TryGetValue("type", out var type) && Equals(type, "error")) return decision;
                return new() { ["type"] = "i1_state", ["state"] = _terminal ?? _nativeCapture(),
                    ["terminal"] = _terminal != null, ["decision"] = decision,
                    ["native_action"] = new { action = nativeAction, args },
                    ["native_ms"] = watch.Elapsed.TotalMilliseconds };
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
        SolverResult result;
        try { result = solver.Solve(); }
        catch (OperationCanceledException) when (cancel.IsCancellationRequested)
        {
            return new() { ["type"] = "i1_plan", ["status"] = "budget_exhausted",
                ["reason"] = "cancelled", ["solve_ms"] = watch.Elapsed.TotalMilliseconds };
        }
        double solveMs = watch.Elapsed.TotalMilliseconds;
        var actions = result.BestNode.Actions;
        var response = new Dictionary<string, object?> {
            ["type"] = "i1_plan", ["status"] = "complete_win", ["solve_ms"] = solveMs,
            ["predicted_win"] = result.Snapshot.AllEnemiesDead && !result.Snapshot.PlayerDead,
            ["transitions"] = result.TransitionCount, ["boundary"] = result.BoundaryReason.ToString(),
            ["encounter"] = live.Encounter?.Id.Entry,
            ["actions"] = actions.Select(a => new { kind = a.Kind.ToString(), a.Turn, a.CardId,
                a.CardOccurrence, a.CardStateKey, a.CardStateOccurrence, a.TargetCombatId,
                a.PotionId, a.PotionSlot, a.Choice, a.NestedChoices, a.TurnStartChoices }).ToArray()
        };
        if (actions.Any(action => (action.Kind is not (PlanActionKind.PlayCard or PlanActionKind.EndTurn or PlanActionKind.UsePotion)
            || (action.Kind == PlanActionKind.UsePotion &&
                (action.PotionId != SupportedPotion || action.PotionSlot < 0 || action.TargetCombatId == null)))
            || action.Choice != null || action.NestedChoices?.Count > 0 || action.TurnStartChoices?.Count > 0))
            return Stop("unsupported", "plan_action_or_choice");
        if (!result.Snapshot.AllEnemiesDead || result.Snapshot.PlayerDead)
        {
            var boundary = result.BoundaryReason;
            return boundary switch
            {
                SearchBoundaryReason.NodeLimit or SearchBoundaryReason.TimeLimit or SearchBoundaryReason.MemoryNoProgress
                    => Stop("budget_exhausted", boundary.ToString()),
                SearchBoundaryReason.UnsupportedEffect or SearchBoundaryReason.PendingChoice or SearchBoundaryReason.DynamicResolution
                    => Stop("unsupported", boundary.ToString()),
                _ => Stop("no_complete_win", boundary.ToString())
            };
        }
        if (actions.Count is < 1 or > 48) return Stop("budget_exhausted", "route_length");

        Dictionary<string, object?> Stop(string status, string reason)
        {
            response["status"] = status;
            response["reason"] = reason;
            return response;
        }
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
                var next = Step(solver, state, action);
                state.ReleaseSimulator();
                state = next;
                frames.Add(Capture());
            }
            if (!state.AllEnemiesDead || state.PlayerDead) throw new InvalidOperationException("Prediction replay did not win");
        }
        finally { state.ReleaseSimulator(); }
        response["ms"] = watch.Elapsed.TotalMilliseconds;
        response["root"] = initial;
        response["frames"] = frames;
        return response;
    }

    private static bool HasChoice(JsonElement action, string field) =>
        action.TryGetProperty(field, out var value) && value.ValueKind != JsonValueKind.Null &&
        (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 0);

    private static Dictionary<string, object?> Rejected(string reason) =>
        new() { ["type"] = "i1_rejected", ["reason"] = reason };

    private static MethodInfo Private(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.NonPublic)!;
    private static MethodInfo Replay => Private(typeof(CombatBeamSolver), "Replay");
    private static MethodInfo Actual => Private(typeof(UnattendedTestRunner), "CaptureActual");
    private static MethodInfo Predicted => Private(typeof(UnattendedTestRunner), "CaptureSimulated");
    private static bool _patched;
    private static CombatState? _boundCombat;
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

// Built only into the isolated probe. The public use_potion adapter may discard on failure.
public partial class RunSimulator
{
    internal Dictionary<string, object?> UseTeacherPotion(Player player, PotionModel potion, int slot, Creature target)
    {
        if (!IsPlayPhase() || HasPendingSelection)
            return Error("Expected an idle player play phase before potion use");

        // Native completion and consumption are necessary. The controller also compares
        // the effect on the target and the full resulting frame before accepting the step.
        int priorShrink = target.GetPowerAmount<MegaCrit.Sts2.Core.Models.Powers.ShrinkPower>();
        var action = new UsePotionAction(potion, target, true);
        bool canceled = false;
        action.BeforeCancelled += _ => canceled = true;
        RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(action);
        WaitForActionExecutor();
        _syncCtx.Pump();

        if (action.Exception is { } exception)
            return ErrorWithTrace("Native potion action failed", exception);
        if (canceled || action.State != GameActionState.Finished ||
            !action.CompletionTask.IsCompletedSuccessfully || HasPendingSelection)
            return Error("Native potion action did not complete at the supported boundary");
        if (player.PotionSlots[slot] != null ||
            target.GetPowerAmount<MegaCrit.Sts2.Core.Models.Powers.ShrinkPower>() <= priorShrink)
            return Error("Native potion did not consume its slot and apply Shrink");
        return DetectDecisionPoint();
    }
}
