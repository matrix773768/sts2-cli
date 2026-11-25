using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;

namespace OfflineSearchHarness;

internal sealed record StructureOptions(string Name, StructureBudget Budget, bool Pair = false,
    bool HotSearch = false, string? PriorHotDraw = null, bool NativeLetter = false, bool PowerControl = false);

internal static partial class HotDrawHarness
{
    private static object RunStructures(string requestPath, UnattendedTestRequest request, HotRootBundle root,
        MainLoopContext loop, CombatState combat)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(requestPath));
        var options = document.RootElement.GetProperty("structureStudy").Deserialize<StructureOptions>(Json)!;
        var budget = options.Budget;
        var session = new Session(root.Rules);
        var trace = new StructureTrace(session, root.Rules);
        var mapping = BindFixtureInstances(request, root);
        var ids = Enumerable.Range(root.RootState.HandCount + 1, request.Cards.Where(card => card.Pile == "Draw")
            .Sum(card => card.Count)).Select(id => (ushort)id);
        var belief = DrawBelief.Create([], ids, []);
        var start = session.Open(root.RootState, root.RootCold, belief, mapping, true);
        var world = session.Open(root.RootState, root.RootCold, belief, mapping, true, keepWorldOrder: true);

        var timer = Stopwatch.StartNew();
        StructureArm battle = new StructureSearch(session, trace, budget, Mode.Ideal, active: false).Run(start);
        StructureArm active = new StructureSearch(session, trace, budget, Mode.Ideal, active: true).Run(start);
        double comparisonMs = timer.Elapsed.TotalMilliseconds;
        object? pair = options.Pair ? CheckPublicPair(session, trace, root, mapping, belief, active, budget) : null;
        object? reference = options.HotSearch ? AnalyzeHotSearch(session, trace, world, budget, loop, combat) : null;
        object? prior = options.PriorHotDraw != null ? AnalyzePrior(session, trace, start, budget, options.PriorHotDraw) : null;
        object? power = options.PowerControl ? CompareBlockedRoot(session, trace, start, budget, root.Rules) : null;
        object? native = options.NativeLetter ? CheckNativeLetter(session, trace, world, root, loop, combat) : null;
        object? randomMiss = options.Name == "conditioned" ? CheckDifferentObservation(session, trace, start, active) : null;
        object? crossover = options.Name == "core500" ? CompareWarmOrders(session, trace, start, budget) : null;

        VerifyExpectedFixture(options.Name, battle, active, pair, power);
        return new
        {
            options.Name,
            rules = "CombatSolver 1.0.2 131d10ae4499b56332787af61fe4a9306e65860f",
            game = "STS2 0.113.1 Build 26660232",
            budget, mode = Mode.Ideal, rootKey = session.PublicKey(start), initial = trace.Frame(start),
            battle, active, comparisonMs, pair, reference, prior, power, native, randomMiss, crossover
        };
    }

    private static void VerifyExpectedFixture(string name, StructureArm battle, StructureArm active, object? pair, object? power)
    {
        bool RealVictory(StructureWitness witness) =>
            witness.Grade == "repeated_to_terminal" && witness.Outcome == HotCombatOutcome.Victory &&
            witness.Laps.Count(lap => lap.Complete) >= 2;
        switch (name)
        {
            case "core50":
            case "core500":
                Check(active.Structures.Any(RealVictory), "The two-card cycle was not independently replayed to victory.");
                Check(battle.Structures.Any(RealVictory), "The victory trace did not expose the two-card cycle.");
                if (name == "core500")
                    Check(active.WinningRoute!.Length > 64, "Long fixture does not exceed the short action budget.");
                break;
            case "energy_limited":
                Check(active.Structures.Any(w => w.Stop == "insufficient_energy" && w.Laps.Count() >= 2 &&
                    w.Kind == "finite_resource"), "Finite loop was not stopped by observed energy exhaustion.");
                break;
            case "block_only":
                Check(active.Structures.Any(w => w.Kind == "block_only" && w.Outcome == HotCombatOutcome.Ongoing),
                    "Pure block fixture must remain a declared block-only candidate.");
                break;
            case "no_draw":
                Check(active.Structures.Length == 0 && power != null, "No Draw control produced a false cycle.");
                break;
            case "ordinary":
                Check(battle.Structures.Length == 0 && active.Structures.Length == 0,
                    "Ordinary deck produced an unexpected repetition.");
                break;
            case "startup_unknown":
                Check(pair != null, "Public pair was not checked.");
                Check(active.Structures.Any(w => RealVictory(w) && w.Startup.Any(step => step.Events.Any(e => e.Kind == EventKind.Draw))),
                    "Startup did not produce a repeated victory after observing unknown cards.");
                break;
            case "quick_kill":
                Check(battle.Structures.Length == 0 && active.Structures.Any(RealVictory),
                    "The short victory control must separate route analysis from discovery.");
                break;
        }
    }

    private static object CompareWarmOrders(Session session, StructureTrace trace, Snapshot root, StructureBudget budget)
    {
        var results = new List<object>();
        foreach (bool first in new[] { true, false })
        {
            foreach (bool active in new[] { first, !first })
            {
                var clock = Stopwatch.StartNew();
                var result = new StructureSearch(session, trace, budget, Mode.Ideal, active).Run(root);
                results.Add(new { active, milliseconds = clock.Elapsed.TotalMilliseconds,
                    result.SearchAndAnalysisMs, result.AnalysisMs, result.ReplayMs, result.AuditMs,
                    result.Nodes, result.SearchAttempts, result.ReplayAttempts, result.AnalysisAttempts,
                    victorySteps = result.WinningRoute?.Length });
            }
        }
        return results;
    }

    private static object CheckDifferentObservation(Session session, StructureTrace trace, Snapshot root, StructureArm active)
    {
        var witness = active.Structures.First(item => item.Outcome == HotCombatOutcome.Victory && item.NontrivialDraws > 0);
        var route = witness.Startup.Concat(witness.Laps.SelectMany(lap => lap.Steps)).ToArray();
        Snapshot state = root;
        for (int i = 0; i < route.Length - 1; i++)
        {
            TraceStep step = route[i];
            var draw = step.Events.SingleOrDefault(e => e.Kind == EventKind.Draw);
            if (i >= witness.Startup.Length && draw is { Result: { } result } &&
                step.Events.All(e => e.Kind != EventKind.PlayerChoice))
            {
                ushort group = draw.Options.Single(option => option.Instance == result).Observation;
                foreach (ushort different in draw.Options.Where(option => option.Observation != group).Select(option => option.Observation).Distinct())
                {
                    var move = session.Actions(state, false).Single(a => trace.Bind(state, a) == step.Move);
                    var alternate = session.Advance(state, move, Prefix.Empty.AddDraw(draw, different));
                    if (alternate.Child == null)
                        continue;
                    Walk following = trace.Replay(alternate.Child, route[i + 1], Mode.Ideal, () => true, strict: false);
                    if (following.Stop != null)
                        return new { step = i, cycleStep = i - witness.Startup.Length,
                            planned = result, different, following.Stop, observation = alternate.Events };
                }
            }
            state = trace.Replay(state, step, Mode.Ideal, () => true, strict: true).State!;
        }
        throw new InvalidOperationException("Could not exercise a different legal observation that breaks the fixed tape.");
    }

    private static object CheckPublicPair(Session session, StructureTrace trace, HotRootBundle root,
        Dictionary<ushort, ushort> mapping, DrawBelief belief, StructureArm original, StructureBudget budget)
    {
        CombatHotState paired = root.RootState;
        for (int i = 0; i < paired.DrawCount / 2; i++)
        {
            int a = paired.DrawStart + i, b = paired.DrawStart + paired.DrawCount - i - 1;
            (paired.Cards[a], paired.Cards[b]) = (paired.Cards[b], paired.Cards[a]);
        }
        paired.Rng[(int)HotRngStream.Shuffle] = HotRng.CreateFromSeed(912886);
        for (int i = 0; i < paired.TotalCardCount; i++)
            paired.Cards[i].CardUid += 100;
        var pairedMapping = mapping.ToDictionary(entry => (ushort)(entry.Key + 100), entry => entry.Value);
        var alternate = session.Open(in paired, root.RootCold, belief, pairedMapping, true);
        var result = new StructureSearch(session, trace, budget, Mode.Ideal, active: true).Run(alternate);
        string Signature(StructureArm arm) => JsonSerializer.Serialize(new
        {
            arm.Stop, arm.Boundaries, arm.Nodes, arm.SearchTransitions,
            witnesses = arm.Structures.Select(w => new { w.Grade, w.Kind, w.Startup, w.Period, w.Laps, w.Stop, w.Outcome }),
            arm.WinningRoute
        }, Json);
        Check(Signature(original) == Signature(result), "Changing the private deck or seed changed public witnesses.");
        return new { equal = true, compared = result.Structures.Length, result.Stop, root = session.PublicKey(alternate) };
    }

    private static object CompareBlockedRoot(Session session, StructureTrace trace, Snapshot blocked,
        StructureBudget budget, HotRules rules)
    {
        CombatHotState copy = blocked.State;
        Check(copy.PowerCount == 1 && rules.Powers[copy.Powers[0].PowerDefId].Entry == "NO_DRAW_POWER",
            "The mirror test requires exactly the intended public Power change.");
        copy.PowerCount = 0;
        copy.ActiveHookMask = HotCombatEngine.RecomputeActiveHookMask(in copy, rules);
        var unblocked = new Snapshot(in copy, blocked.Cold, blocked.Belief);
        var control = new StructureSearch(session, trace, budget, Mode.Ideal, active: true).Run(unblocked);
        var witness = control.Structures.First(w => w.Outcome == HotCombatOutcome.Victory);
        Walk interrupted = trace.Replay(blocked, witness.Period[0], Mode.Ideal, () => true, strict: false);
        Check(interrupted.Stop == "draw_blocked_by_power", $"Expected explicit Power interruption, observed {interrupted.Stop}.");
        return new { world = "remove the one named Power before the control run", controlRoot = trace.Frame(unblocked),
            control = witness, interrupted.Stop };
    }

    private static object AnalyzePrior(Session session, StructureTrace trace, Snapshot root,
        StructureBudget budget, string file)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(file));
        WitnessStep[] source = document.RootElement.GetProperty("fixtures").GetProperty("pair").GetProperty("result")
            .GetProperty("ideal").GetProperty("Best").GetProperty("Witness").Deserialize<WitnessStep[]>(Json)!;
        var route = new List<TraceStep>();
        Snapshot state = root;
        foreach (WitnessStep step in source)
        {
            HotAction action = session.Actions(state, false).Single(a => session.ActionName(state, a) == step.Action);
            Prefix prefix = new(step.Events.Where(e => e.Kind == EventKind.Draw)
                .Select(e => new DrawInput(e.Address, e.Result!.Value)).ToArray(),
                step.Events.Where(e => e.Kind == EventKind.PlayerChoice)
                .Select(e => new ChoiceInput(e.Address, e.Selection!)).ToArray());
            Transition result = Status(session.Advance(state, action, prefix), StepStatus.Completed);
            Check(JsonSerializer.Serialize(result.Events, Json) == JsonSerializer.Serialize(step.Events, Json),
                "Recorded N2A.1 trace was not reproduced.");
            route.Add(trace.Record(state, action, result));
            state = result.Child!;
        }
        return new StructureSearch(session, trace, budget, Mode.Ideal, active: false).Analyze(root, route.ToArray());
    }

    private static object AnalyzeHotSearch(Session session, StructureTrace trace, Snapshot root,
        StructureBudget budget, MainLoopContext loop, CombatState combat)
    {
        var clock = Stopwatch.StartNew();
        var result = ModRuntime.RunSearchDetailed(combat, new HarnessOptions
        {
            Profile = "Custom", Beam = 24, Nodes = 4096, BudgetMilliseconds = 375,
            PotionPolicy = "Disabled", SearchMode = "Coordinator", MaxDegreeOfParallelism = 1
        }, loop, null);
        double milliseconds = clock.Elapsed.TotalMilliseconds;
        var route = new List<TraceStep>();
        Snapshot state = root;
        string? stop = null;
        foreach (PlanAction planned in result.Result.BestNode.Actions)
        {
            if (planned.Kind != PlanActionKind.PlayCard || planned.GetActionChoicesInExecutionOrder().Count != 0)
            {
                stop = "plan_action_outside_reference_adapter";
                break;
            }
            // This reference adapter imports the unique-instance, no-choice core fixture.
            // It verifies target and legality afresh. Ambiguous materialization fails closed.
            var matching = session.Actions(state, false).Where(action =>
            {
                var bound = trace.Bind(state, action);
                return bound.Card == planned.CardId &&
                    (planned.TargetCombatId == null || (bound.Target >= 0 &&
                     state.State.Enemies[bound.Target].Vital.CombatId == planned.TargetCombatId));
            }).ToArray();
            if (matching.Length != 1)
            {
                stop = "ambiguous_or_missing_plan_instance";
                break;
            }

            Transition step = session.Advance(state, matching[0], Prefix.Empty, Resolution.CaptureWorld);
            if (step.Status != StepStatus.Completed)
            {
                stop = $"plan_replay_boundary:{step.Status}:{step.Reason}";
                break;
            }
            route.Add(trace.Record(state, matching[0], step));
            state = step.Child!;
        }
        return new
        {
            milliseconds, productionBoundary = result.Result.BoundaryReason.ToString(),
            imported = route.Count, stop, terminal = state.State.TerminalOutcome,
            metrics = result.LegacyMetrics,
            structures = new StructureSearch(session, trace, budget, Mode.Oracle, active: false).Analyze(root, route.ToArray())
        };
    }

    private static object CheckNativeLetter(Session session, StructureTrace trace, Snapshot world,
        HotRootBundle original, MainLoopContext loop, CombatState combat)
    {
        Snapshot state = world;
        var player = LocalContext.GetMe(combat)!;
        var deltas = new List<long>();
        for (int i = 0; i < 3; i++)
        {
            HotAction action = session.Actions(state, false).Single();
            Transition expected = Status(session.Advance(state, action, Prefix.Empty, Resolution.CaptureWorld), StepStatus.Completed);
            var played = player.PlayerCombatState!.Hand.Cards.Single();
            var outcome = RealCombatDriver.RunRealCombatAction(loop, combat, RealCombatAction.PlayCard(played, null),
                TimeSpan.FromSeconds(5));
            var actual = HotRootBuilder.BuildFromLive(combat);
            Check(outcome == expected.Outcome, "Native delayed-relic outcome diverged.");
            Check(AuditFrame(original.Rules, in expected.Child!.State, expected.Child.Cold) ==
                AuditFrame(actual.Rules, actual.RootState, actual.RootCold), "Native delayed-relic frame diverged.");
            deltas.Add(trace.Delta(state, expected.Child).EnemyDurabilityRemoved);
            state = expected.Child;
        }
        Check(deltas.SequenceEqual(new long[] {0, 0, 5}), "Letter Opener should pay on the third skill.");
        return new { comparedNativeActions = 3, observedDamage = deltas };
    }
}
