using System.Diagnostics;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Models;
using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Runs;

namespace OfflineSearchHarness;

internal static class DistributionProbe
{
    private static readonly MethodInfo Replay = PrivateMethod(typeof(CombatBeamSolver), "Replay");
    private static readonly MethodInfo Actual = PrivateMethod(typeof(UnattendedTestRunner), "CaptureActual");
    private static readonly MethodInfo Predicted = PrivateMethod(typeof(UnattendedTestRunner), "CaptureSimulated");
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };
    private static Func<JsonObject>? _captureTerminal;
    private static JsonObject? _nativeTerminal;

    internal static void Run(CombatState live, MainLoopContext loop, string output)
    {
        Player player = live.Players.Single();
        Creature enemy = live.Enemies.Single();
        var root = CombatRootSnapshot.Capture(live);
        var policy = SolverController.CaptureSearchPolicy(SolverSettings.Capture(), live,
            includeTurnSetup: false, theftPolicy: SolverController.ResolveTheftPolicy(live));
        var names = SolverDisplayNames.Capture(live);
        var damage = BattleDamageTracker.Observe(live);
        CombatBeamSolver Solver() => new(root, names, damage, policy, CancellationToken.None, searchProfile: policy.Profile);

        var cards = player.PlayerCombatState!.DrawPile.Cards.ToArray();
        string[] deck = cards.Select(card => card.Id.Entry).ToArray();
        int[] identity = Enumerable.Range(0, 5).ToArray();
        if (!deck.SequenceEqual(new[] { "BASH", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "STRIKE_IRONCLAD" }))
            throw new InvalidOperationException("Unexpected CS3 draw pile.");
        var publicRoot = new { id = "cs3-m1cs1", seed = "M1CS1", encounter = "FUZZY_WURM_CRAWLER_WEAK",
            character = "IRONCLAD", hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp,
            gold = player.Gold, energy = player.PlayerCombatState.Energy,
            hand = player.PlayerCombatState.Hand.Cards.Select(card => card.Id.Entry).ToArray(),
            knownDrawMultiset = deck.Order(StringComparer.Ordinal).ToArray(), enemyHp = enemy.CurrentHp,
            intent = "FIRST_ACID_GOOP", relics = player.Relics.Select(relic => relic.Id.Entry).ToArray() };
        string? nativeOrder = Environment.GetEnvironmentVariable("M1CS4_NATIVE_ORDER");
        if (!string.IsNullOrEmpty(nativeOrder))
        {
            int[] order = nativeOrder.Split(',').Select(int.Parse).ToArray();
            if (!order.Order().SequenceEqual(identity)) throw new InvalidOperationException("Invalid permutation.");
            var route = Rollout(Solver(), player, order, 1, capture: true);
            Write(output, "expected-route.json", route);
            Write(output, "native.json", new { route, native = Native(live, player, enemy, loop, order, route, output) });
            return;
        }

        string stamp = ContinuationStamp.CaptureLive(live).StateText;
        var comparer = root.ForkSimulator().State.GetPlayerCombatState(player).DrawPile.Cards;
        string[] strikeKeys = comparer.Skip(2).Select(CardChoiceSupport.ChoiceCardKey).ToArray();
        if (strikeKeys.Distinct().Count() != 1) throw new InvalidOperationException("Strike semantic keys differ.");
        int[][] allOrders = Permutations(identity).ToArray();
        var groups = allOrders.GroupBy(order => string.Join("/", order.Select(index => deck[index]))).ToArray();
        for (int i = 0; i < 5; i++) Rollout(Solver(), player, identity, 1);
        long start = Stopwatch.GetTimestamp();
        var merged = groups.Select(group => Rollout(Solver(), player, group.First(), group.Count())).ToArray();
        double mergedMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        start = Stopwatch.GetTimestamp();
        var exhaustive = allOrders.Select(order => Rollout(Solver(), player, order, 1)).ToArray();
        double exhaustiveMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        var representatives = merged.ToDictionary(row => string.Join("/", row.Order.Select(index => deck[index])));
        int differences = exhaustive.Count(row => {
            var expected = representatives[string.Join("/", row.Order.Select(index => deck[index]))];
            return row.End != expected.End || !row.Actions.SequenceEqual(expected.Actions);
        });
        if (stamp != ContinuationStamp.CaptureLive(live).StateText)
            throw new InvalidOperationException("Enumeration changed the native root.");
        Write(output, "batch.json", new { schemaVersion = 1, policyVersion = "leftmost-legal/v1",
            distribution = "uniform-labelled-permutations-of-cs3-hidden-draw-pile/v1",
            publicRoot, strikeKeys, differences, mergedMs, exhaustiveMs, merged, exhaustive });
    }

    private static object Native(CombatState live, Player player, Creature enemy, MainLoopContext loop, int[] order, RolloutRow route, string output)
    {
        var draw = player.PlayerCombatState!.DrawPile;
        var cards = draw.Cards.ToArray();
        foreach (var card in cards) draw.RemoveInternal(card, silent: true);
        foreach (int i in order) draw.AddInternal(cards[i], -1, silent: true);
        if (!draw.Cards.SequenceEqual(order.Select(i => cards[i])))
            throw new InvalidOperationException("Native scenario did not receive the requested entity order.");
        List<object> checks = [];
        string? failure = null;
        var manager = CombatManager.Instance;
        var executor = RunManager.Instance.ActionExecutor;
        var method = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
            .Single(method => method.Name == "EndCombatInternal" && method.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
        var prefix = PrivateMethod(typeof(DistributionProbe), nameof(ObserveTerminal));
        var patch = new Harmony("m1-cs4.native-terminal");
        var actualStart = Capture(Actual, live, player, enemy);
        var rootDifferences = Differences(route.RootState!, actualStart);
        int step = 0;
        _captureTerminal = () =>
        {
            var terminal = Capture(Actual, live, player, enemy);
            Write(output, "native-terminal.json", new { terminal, differences = Differences(route.States![^1], terminal) });
            return terminal;
        };
        _nativeTerminal = null;
        patch.Patch(method, prefix: new HarmonyMethod(prefix));
        var wrapper = typeof(CardModel).GetMethod("OnPlayWrapper", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!;
        var moveNext = wrapper.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType
            .GetMethod("MoveNext", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var timerPatch = PrivateMethod(typeof(DistributionProbe), nameof(ReplaceGodotTimer));
        patch.Patch(moveNext, transpiler: new HarmonyMethod(timerPatch));
        var replayWriter = AccessTools.Method(typeof(RunManager), "WriteReplay", [typeof(bool)]);
        var hoverClear = AccessTools.Method(AccessTools.TypeByName("NHoverTipSet"), "Clear", []);
        var skipHostSideEffect = PrivateMethod(typeof(DistributionProbe), nameof(SkipHostSideEffect));
        patch.Patch(replayWriter, prefix: new HarmonyMethod(skipHostSideEffect));
        patch.Patch(hoverClear, prefix: new HarmonyMethod(skipHostSideEffect));
        try
        {
            foreach (var action in route.Actions)
            {
                int index = step++;
                Write(output, "native-progress.json", new { attempted = step, action, rootDifferences, actualStart, checks });
                var pcs = player.PlayerCombatState!;
                if (!manager.IsInProgress || pcs.TurnNumber != action.Turn)
                    throw new InvalidOperationException("Native play boundary or turn differs.");
                if (action.Kind == "EndTurn")
                {
                    manager.OnEndedTurnLocally();
                    RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new EndPlayerTurnAction(player, action.Turn));
                }
                else
                {
                    var card = pcs.Hand.Cards.Where(card => card.Id.Entry == action.CardId).ElementAt(action.Occurrence);
                    var target = action.Target == null ? null : enemy;
                    if (!card.CanPlayTargeting(target) || !card.TryManualPlay(target))
                        throw new InvalidOperationException("Native rejected " + action.CardId);
                }
                loop.RunUntilCompleted(executor.FinishedExecutingActions(), TimeSpan.FromSeconds(4), "native action");
                if (action.Kind == "EndTurn")
                {
                    var deadline = Stopwatch.StartNew();
                    while (manager.IsInProgress && (pcs.TurnNumber <= action.Turn || pcs.Phase != PlayerTurnPhase.Play))
                    {
                        if (deadline.Elapsed.TotalSeconds > 4) throw new TimeoutException("Native next player turn absent.");
                        loop.Pump(TimeSpan.FromMilliseconds(10));
                    }
                }
                var actual = _nativeTerminal ?? Capture(Actual, live, player, enemy);
                var expected = route.States![index];
                checks.Add(new { step, action, differences = Differences(expected, actual),
                    expected, actual, terminal = _nativeTerminal != null });
            }
        }
        catch (Exception error)
        {
            failure = error.ToString();
        }
        finally
        {
            patch.Unpatch(hoverClear, skipHostSideEffect);
            patch.Unpatch(replayWriter, skipHostSideEffect);
            patch.Unpatch(moveNext, timerPatch);
            patch.Unpatch(method, prefix);
            _captureTerminal = null;
        }
        return new { rootDifferences, actualStart, attempted = step, completed = checks.Count,
            checks, failure, observedNativeTerminal = _nativeTerminal != null,
            terminalSnapshot = _nativeTerminal,
            terminalDifferences = _nativeTerminal == null ? null : Differences(route.States![^1], _nativeTerminal),
            nativeCombatStillInProgress = manager.IsInProgress, postCombatHp = player.Creature.CurrentHp };
    }

    private static IEnumerable<CodeInstruction> ReplaceGodotTimer(IEnumerable<CodeInstruction> instructions)
    {
        foreach (var instruction in instructions)
        {
            if (instruction.operand is MethodInfo method && method.DeclaringType?.FullName == "Godot.Time"
                && method.Name == "GetTicksMsec")
            {
                instruction.opcode = OpCodes.Call;
                instruction.operand = PrivateMethod(typeof(DistributionProbe), nameof(ManagedMilliseconds));
            }
            yield return instruction;
        }
    }

    private static bool SkipHostSideEffect() => false;

    private static ulong ManagedMilliseconds() => (ulong)Environment.TickCount64;
    private static void ObserveTerminal()
    {
        _nativeTerminal ??= _captureTerminal?.Invoke();
    }

    private static string[] Differences(JsonObject expected, JsonObject actual)
        => expected.Select(pair => pair.Key).Union(actual.Select(pair => pair.Key))
            .Where(key => !JsonNode.DeepEquals(expected[key], actual[key])).ToArray();

    private static JsonObject Capture(MethodInfo method, params object[] args)
        => JsonSerializer.SerializeToNode(method.Invoke(null, args), Json)!.AsObject();

    private static RolloutRow Rollout(CombatBeamSolver solver, Player player, int[] order, int weight, bool capture = false)
    {
        long timestamp = Stopwatch.GetTimestamp();
        var state = Step(solver, null, null);
        var sim = (CombatPredictionSimulator)state.Simulator;
        var draw = sim.State.GetPlayerCombatState(player).DrawPile;
        var cards = draw.Cards.ToArray();
        draw.Clear();
        foreach (int index in order) draw.Add(cards[index]);
        JsonObject? ReadState()
        {
            if (!capture) return null;
            var engine = (CombatPredictionSimulator)state.Simulator;
            var combat = (SimulatedCombatState)engine.State.CombatState;
            var monster = ((SimulatedCombatState)sim.State.CombatState).KnownEnemies.Single();
            return Capture(Predicted, engine, combat, player, monster);
        }
        var initial = ReadState();
        List<ActionRow> actions = [];
        List<JsonObject>? states = capture ? [] : null;
        string? failure = null;
        try
        {
            while (actions.Count < 100 && !state.AllEnemiesDead && !state.PlayerDead
                && state.BoundaryReason == SearchBoundaryReason.None)
            {
                var action = Choose((CombatPredictionSimulator)state.Simulator, player, state.Turn);
                var next = Step(solver, state, action);
                actions.Add(new(action.Kind.ToString(), action.Turn, action.CardId, action.CardOccurrence, action.TargetCombatId));
                state.ReleaseSimulator();
                state = next;
                if (states != null) states.Add(ReadState()!);
            }
        }
        catch (Exception error)
        {
            failure = error.GetBaseException().Message;
        }
        if (!state.AllEnemiesDead && !state.PlayerDead)
            failure ??= state.BoundaryReason == SearchBoundaryReason.None ? "ActionLimit" : state.BoundaryReason.ToString();
        var end = new EndRow(state.AllEnemiesDead, state.PlayerDead, state.PlayerHp, state.EnemyHp,
            state.CumulativePlayerHpLost, state.RecoveredPlayerHp, state.Turn, 0,
            state.GrowthRewards.Total, state.LongTermResourceValue, state.HasRisk, failure);
        state.ReleaseSimulator();
        return new(order, string.Join(",", order), weight, 120, actions.ToArray(), end,
            Stopwatch.GetElapsedTime(timestamp).TotalMilliseconds, actions.Count, initial, states);
    }

    private static PlanAction Choose(CombatPredictionSimulator sim, Player player, int turn)
    {
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var hand = sim.State.GetPlayerCombatState(player).Hand.Cards;
        Dictionary<string, int> occurrences = new(StringComparer.Ordinal);
        foreach (var card in hand)
        {
            string id = card.Preview.Id.Entry;
            int occurrence = occurrences.GetValueOrDefault(id);
            if (combat.CanPlayCard(sim, card))
            {
                uint? target = id == "DEFEND_IRONCLAD" ? null : combat.Enemies.Single().CombatId;
                return new PlanAction(PlanActionKind.PlayCard, turn, id, occurrence, TargetCombatId: target);
            }
            occurrences[id] = occurrence + 1;
        }
        return new PlanAction(PlanActionKind.EndTurn, turn);
    }

    private static SimulationSnapshot Step(CombatBeamSolver solver, SimulationSnapshot? parent, PlanAction? action)
    {
        object?[] args = Enumerable.Repeat<object?>(Type.Missing, Replay.GetParameters().Length).ToArray();
        args[0] = action == null ? Array.Empty<PlanAction>() : new[] { action };
        args[1] = parent;
        if (parent != null) args[2] = parent.Turn;
        return (SimulationSnapshot)Replay.Invoke(solver, args)!;
    }

    private static IEnumerable<int[]> Permutations(int[] values)
    {
        if (values.Length == 0) { yield return []; yield break; }
        foreach (int head in values)
            foreach (int[] tail in Permutations(values.Where(value => value != head).ToArray()))
                yield return [head, ..tail];
    }

    private static MethodInfo PrivateMethod(Type type, string name)
        => type.GetMethod(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.NonPublic)!;

    private static void Write(string output, string name, object data)
        => File.WriteAllText(Path.Combine(output, name), JsonSerializer.Serialize(data, Json));

    private sealed record ActionRow(string Kind, int Turn, string CardId, int Occurrence, uint? Target);
    private sealed record EndRow(bool Won, bool Dead, int Hp, int EnemyHp, int Loss, int Recovered,
        int Turn, int PotionsUsed, int Growth, int LongTermResourceValue, bool Risk, string? Failure);
    private sealed record RolloutRow(int[] Order, string ScenarioId, int WeightNumerator, int WeightDenominator,
        ActionRow[] Actions, EndRow End, double Milliseconds, int Transitions, JsonObject? RootState, List<JsonObject>? States);
}
