using System.Diagnostics;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

internal static partial class DistributionProbe
{
    private static bool _stopBeforeDraw;
    private static readonly string[] Types = ["BASH", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"];

    private sealed record Opening(string Hand, int Weight, string[] Orders);
    private sealed record Leaf(int Loss, int Hp, int EnemyHp, int EnemyBlock, string PlayerPowers,
        string EnemyPowers, bool Won, bool Dead, int Turn, string Boundary, PlanAction[] Route);
    private sealed record SearchSample(string Order, bool Cache, int Nodes, int DistinctKeys, int Transitions,
        int CacheHits, int Cutoffs, int InvalidBoundaries, int MaxTurn, bool BudgetHit, double Milliseconds,
        Leaf? Best, Leaf[] Frontier);

    internal static void RunSeapunk(CombatState live, MainLoopContext loop, string output)
    {
        var player = live.Players.Single();
        var enemy = live.Enemies.Single();
        var pcs = player.PlayerCombatState!;
        var available = pcs.Hand.Cards.Concat(pcs.DrawPile.Cards).ToArray();
        if (enemy.Monster?.Id.Entry != "SEAPUNK" || enemy.CurrentHp != 45
            || player.Creature.CurrentHp != 80 || player.Gold != 99
            || pcs.Energy != 3 || pcs.TurnNumber != 1
            || !player.Relics.Select(relic => relic.Id.Entry).SequenceEqual(new[] { "BURNING_BLOOD" })
            || player.PotionSlots.Any(potion => potion != null)
            || !available.GroupBy(card => card.Id.Entry).OrderBy(group => group.Key)
                .Select(group => group.Count()).SequenceEqual(new[] { 1, 4, 5 }))
            throw new InvalidOperationException("Unexpected frozen Seapunk root.");

        var groups = CardOrders(1, 4, 5).GroupBy(order => SortHand(order[..5]))
            .Select(group => new Opening(group.Key, group.Count(), group.ToArray())).ToArray();
        var policy = SolverController.CaptureSearchPolicy(SolverSettings.Capture(), live,
            includeTurnSetup: false, theftPolicy: SolverController.ResolveTheftPolicy(live));
        var names = SolverDisplayNames.Capture(live);
        var damage = BattleDamageTracker.Observe(live);
        var mode = Environment.GetEnvironmentVariable("M1CS5_MODE") ?? "grouped";
        var root = CombatRootSnapshot.Capture(live);
        var rootSim = root.ForkSimulator();
        var keys = rootSim.State.GetPlayerCombatState(player).Hand.Cards.Concat(rootSim.State.GetPlayerCombatState(player).DrawPile.Cards)
            .GroupBy(card => card.Preview.Id.Entry).ToDictionary(group => group.Key,
                group => group.Select(CardChoiceSupport.ChoiceCardKey).Distinct().ToArray());
        if (!keys.Keys.Order().SequenceEqual(Types) || keys.Values.Any(cardKeys => cardKeys.Length != 1))
            throw new InvalidOperationException("Starter cards do not meet duplicate-copy equivalence.");
        CombatBeamSolver Solver() => new(root, names, damage, policy, CancellationToken.None, searchProfile: policy.Profile);

        var stop = PrivateMethod(typeof(CombatBeamSolver), "AdvanceRoundPlayerStart");
        var prefix = PrivateMethod(typeof(DistributionProbe), nameof(StopBeforeThirdDraw));
        Harmony harmony = new("m1-cs5.horizon");
        harmony.Patch(stop, prefix: new HarmonyMethod(prefix));
        try
        {
            if (mode.StartsWith("native-", StringComparison.Ordinal))
            {
                string order = mode == "native-a" ? "BDDDSDSSSS" : "SSSSSBDDDD";
                SetNativeOrder(player, available, order);
                root = CombatRootSnapshot.Capture(live);
                var candidate = Search(Solver(), player, order, horizon: false, cache: false, nodeLimit: 3000, seconds: 6);
                if (candidate.Best is not { Won: true } win)
                {
                    Write(output, "solution.json", candidate);
                    return;
                }
                var trace = Trace(Solver(), player, win);
                Write(output, "expected-route.json", trace);
                Write(output, "native.json", new { candidate, native = Native(live, player, enemy, loop, [0,1,2,3,4], trace, output) });
                return;
            }

            // Restrict the expensive full search to two explicit orders, with and without reuse.
            if (mode == "full")
            {
                string[] orders = ["BDDDSDSSSS", "SSSSSBDDDD"];
                var comparisons = orders.Select(order => new {
                    order, independent = Search(Solver(), player, order, false, false, 3000, 6),
                    cached = Search(Solver(), player, order, false, true, 3000, 6)
                }).ToArray();
                Write(output, "solution.json", new { comparisons, peakMiB = PeakMiB() });
                return;
            }

            var warm = Search(Solver(), player, groups[0].Orders[0], true, false, 20000, 20);
            if (warm.BudgetHit || warm.InvalidBoundaries > 0) throw new InvalidOperationException("Horizon warmup incomplete.");
            long start = Stopwatch.GetTimestamp();
            var rows = groups.Select(group => new {
                group.Hand, group.Weight, matchedOrderCount = Matched(group).Count(),
                searches = (mode == "grouped" ? group.Orders.Take(1) : Matched(group))
                    .Select(order => Search(Solver(), player, order, true, false, 20000, 20)).ToArray()
            }).ToArray();
            double milliseconds = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            Write(output, "solution.json", new { mode, totalOrders = groups.Sum(group => group.Weight),
                milliseconds, peakMiB = PeakMiB(), cardKeys = keys, rows });
        }
        finally { harmony.Unpatch(stop, prefix); }
    }

    private static IEnumerable<string> Matched(Opening group)
        => new[] { group.Orders[0], group.Orders[group.Orders.Length / 2], group.Orders[^1] }.Distinct();

    private static bool StopBeforeThirdDraw(ref SearchBoundaryReason __result)
    {
        if (!_stopBeforeDraw) return true;
        __result = SearchBoundaryReason.TurnLimit;
        return false;
    }

    private static SearchSample Search(CombatBeamSolver solver, Player player, string order,
        bool horizon, bool cache, int nodeLimit, int seconds)
    {
        long start = Stopwatch.GetTimestamp();
        int nodes = 0, transitions = 0, hits = 0, cutoffs = 0, invalid = 0, maxTurn = 0;
        bool budget = false;
        HashSet<(StateFingerprint, int)> keys = [];
        HashSet<(StateFingerprint, string, int)> checkedStates = [];
        Dictionary<(int, int, int, string, string, bool, bool), Leaf> endpoints = [];
        Leaf? best = null;
        List<PlanAction> path = [];
        var root = Step(solver, null, null);
        SetPredictedOrder(root, player, order);
        Visit(root);
        root.ReleaseSimulator();

        var frontier = horizon ? endpoints.Values.OrderBy(leaf => leaf.Loss).ThenBy(leaf => leaf.EnemyHp).ToArray() : [];
        return new(order, cache, nodes, keys.Count, transitions, hits, cutoffs, invalid, maxTurn, budget,
            Stopwatch.GetElapsedTime(start).TotalMilliseconds, best, frontier);

        void Visit(SimulationSnapshot state)
        {
            if (nodes >= nodeLimit || Stopwatch.GetElapsedTime(start).TotalSeconds >= seconds)
            {
                budget = true;
                return;
            }
            nodes++;
            maxTurn = Math.Max(maxTurn, state.Turn);
            // The initial Replay built its key before test-only pile injection.
            if (path.Count != 0) keys.Add((state.StateKey, state.CumulativePlayerHpLost));
            if (state.HasRisk || (state.BoundaryReason != SearchBoundaryReason.None
                && !(horizon && state.BoundaryReason == SearchBoundaryReason.TurnLimit)))
            {
                invalid++;
                return;
            }
            if (state.AllEnemiesDead || state.PlayerDead || state.BoundaryReason != SearchBoundaryReason.None)
            {
                var leaf = MakeLeaf(state, player, path);
                if (horizon)
                {
                    endpoints.TryAdd((leaf.Loss, leaf.EnemyHp, leaf.EnemyBlock, leaf.PlayerPowers,
                        leaf.EnemyPowers, leaf.Won, leaf.Dead), leaf);
                    if (best == null || (leaf.Loss, leaf.EnemyHp).CompareTo((best.Loss, best.EnemyHp)) < 0)
                        best = leaf;
                }
                else if (leaf.Won && (best == null || leaf.Loss < best.Loss)) best = leaf;
                return;
            }
            if (!horizon && (state.Turn > 6 || (best != null && state.CumulativePlayerHpLost >= best.Loss)))
            {
                cutoffs++;
                if (state.Turn > 6) budget = true;
                return;
            }
            var sim = (CombatPredictionSimulator)state.Simulator;
            var combat = (SimulatedCombatState)sim.State.CombatState;
            if (cache && path.Count > 0)
            {
                var key = (state.StateKey, Capture(Predicted, sim, combat, player, combat.KnownEnemies.Single()).ToJsonString(),
                    state.CumulativePlayerHpLost);
                if (!checkedStates.Add(key)) { hits++; return; }
            }
            foreach (var action in Legal(sim, combat, player, state.Turn))
            {
                if (nodes >= nodeLimit || Stopwatch.GetElapsedTime(start).TotalSeconds >= seconds) { budget = true; break; }
                _stopBeforeDraw = horizon && state.Turn == 2 && action.Kind == PlanActionKind.EndTurn;
                SimulationSnapshot next;
                try { next = Step(solver, state, action); }
                finally { _stopBeforeDraw = false; }
                transitions++;
                path.Add(action);
                Visit(next);
                path.RemoveAt(path.Count - 1);
                next.ReleaseSimulator();
                if (!horizon && best is { Loss: 0 }) break;
            }
        }
    }

    private static IEnumerable<PlanAction> Legal(CombatPredictionSimulator sim, SimulatedCombatState combat, Player player, int turn)
    {
        var hand = sim.State.GetPlayerCombatState(player).Hand.Cards;
        foreach (string id in Types)
        {
            var card = hand.FirstOrDefault(item => item.Preview.Id.Entry == id);
            if (card != null && combat.CanPlayCard(sim, card))
                yield return new PlanAction(PlanActionKind.PlayCard, turn, id,
                    TargetCombatId: id == "DEFEND_IRONCLAD" ? null : combat.Enemies.Single().CombatId);
        }
        yield return new PlanAction(PlanActionKind.EndTurn, turn);
    }

    private static Leaf MakeLeaf(SimulationSnapshot state, Player player, List<PlanAction> path)
    {
        var sim = (CombatPredictionSimulator)state.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var enemy = combat.KnownEnemies.Single();
        string Powers(MegaCrit.Sts2.Core.Entities.Creatures.Creature creature)
            => string.Join(",", combat.EffectivePowers().Where(power => ReferenceEquals(power.Owner, creature))
                .Select(power => $"{power.Id.Entry}:{power.Amount}").Order());
        return new(state.CumulativePlayerHpLost, state.PlayerHp, state.EnemyHp, sim.State.GetCreature(enemy).Block,
            Powers(player.Creature), Powers(enemy), state.AllEnemiesDead, state.PlayerDead, state.Turn,
            state.BoundaryReason.ToString(), path.ToArray());
    }

    private static void SetPredictedOrder(SimulationSnapshot state, Player player, string order)
    {
        var pcs = ((CombatPredictionSimulator)state.Simulator).State.GetPlayerCombatState(player);
        var byType = pcs.Hand.Cards.Concat(pcs.DrawPile.Cards).GroupBy(card => card.Preview.Id.Entry)
            .ToDictionary(group => group.Key, group => new Queue<CombatSolver.Engine.Common.PredictedCard>(group));
        pcs.Hand.Clear();
        pcs.DrawPile.Clear();
        for (int i = 0; i < order.Length; i++)
            (i < 5 ? pcs.Hand : pcs.DrawPile).Add(byType[Id(order[i])].Dequeue());
    }

    private static void SetNativeOrder(Player player, CardModel[] cards, string order)
    {
        var pcs = player.PlayerCombatState!;
        var byType = cards.GroupBy(card => card.Id.Entry).ToDictionary(group => group.Key, group => new Queue<CardModel>(group));
        foreach (var card in pcs.Hand.Cards.ToArray()) pcs.Hand.RemoveInternal(card, silent: true);
        foreach (var card in pcs.DrawPile.Cards.ToArray()) pcs.DrawPile.RemoveInternal(card, silent: true);
        for (int i = 0; i < order.Length; i++)
            (i < 5 ? pcs.Hand : pcs.DrawPile).AddInternal(byType[Id(order[i])].Dequeue(), -1, silent: true);
    }

    private static RolloutRow Trace(CombatBeamSolver solver, Player player, Leaf win)
    {
        var state = Step(solver, null, null);
        System.Text.Json.Nodes.JsonObject Read()
        {
            var sim = (CombatPredictionSimulator)state.Simulator;
            var combat = (SimulatedCombatState)sim.State.CombatState;
            return Capture(Predicted, sim, combat, player, combat.KnownEnemies.Single());
        }
        var root = Read();
        List<ActionRow> actions = [];
        List<System.Text.Json.Nodes.JsonObject> snapshots = [];
        foreach (var action in win.Route)
        {
            var next = Step(solver, state, action);
            state.ReleaseSimulator();
            state = next;
            actions.Add(new(action.Kind.ToString(), action.Turn, action.CardId, action.CardOccurrence, action.TargetCombatId));
            snapshots.Add(Read());
        }
        var end = new EndRow(state.AllEnemiesDead, state.PlayerDead, state.PlayerHp, state.EnemyHp, state.CumulativePlayerHpLost,
            state.RecoveredPlayerHp, state.Turn, 0, state.GrowthRewards.Total, state.LongTermResourceValue, state.HasRisk, null);
        state.ReleaseSimulator();
        if (!end.Won || end.Loss != win.Loss) throw new InvalidOperationException("Native trace did not reproduce the predicted solution.");
        return new([0,1,2,3,4], "seapunk", 1, 1260, actions.ToArray(), end, 0, actions.Count, root, snapshots);
    }

    private static double PeakMiB() => Process.GetCurrentProcess().PeakWorkingSet64 / 1048576.0;
    private static string SortHand(string hand) => new(hand.Order().ToArray());
    private static string Id(char token) => token switch { 'B' => Types[0], 'D' => Types[1], 'S' => Types[2], _ => throw new ArgumentException(nameof(token)) };

    private static IEnumerable<string> CardOrders(int bash, int defend, int strike)
    {
        if (bash + defend + strike == 0) { yield return ""; yield break; }
        if (bash > 0) foreach (string tail in CardOrders(bash - 1, defend, strike)) yield return "B" + tail;
        if (defend > 0) foreach (string tail in CardOrders(bash, defend - 1, strike)) yield return "D" + tail;
        if (strike > 0) foreach (string tail in CardOrders(bash, defend, strike - 1)) yield return "S" + tail;
    }
}
