using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using CombatSolver;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;

namespace OfflineSearchHarness;

internal static partial class HotDrawHarness
{
    private static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() }
    };

    public static int Run(string fixture, string requestPath, string resultPath)
    {
        var clock = Stopwatch.StartNew();
        var loop = new MainLoopContext();
        string output = Path.GetDirectoryName(Path.GetFullPath(resultPath))!;
        Directory.CreateDirectory(output);
        GameBootstrap.EnsureBootstrapped(loop, new HarnessOptions
        {
            OutputDirectory = output, WorkspaceDirectory = output, Language = "en"
        });
        var request = GeneratedScenarioSetup.ReadRequest(requestPath);
        var setup = GeneratedScenarioSetup.Prepare(request, output);
        var entered = setup.EnterCombatRoomAsync();
        loop.RunUntilCompleted(entered, TimeSpan.FromSeconds(20), "HotDraw fixture");
        using var setupChoices = entered.GetAwaiter().GetResult();
        var combat = OfflineCombat.WaitForPlayableCombat(loop);
        var player = LocalContext.GetMe(combat)!;
        loop.RunUntilCompleted(setup.Session.InjectInitialStateAsync(combat, player),
            TimeSpan.FromSeconds(15), "HotDraw initial state");
        HotRootBundle root = HotRootBuilder.BuildFromLive(combat);
        double coldMilliseconds = clock.Elapsed.TotalMilliseconds;
        object result = RunFixture(fixture, request, root, loop, combat);
        using var outputStream = new FileStream(resultPath, FileMode.CreateNew);
        JsonSerializer.Serialize(outputStream, new { fixture, coldMilliseconds, result }, Json);
        return 0;
    }

    private static object RunFixture(string fixture, UnattendedTestRequest request, HotRootBundle root, MainLoopContext loop,
        MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var session = new Session(root.Rules);
        var stableIds = BindFixtureInstances(request, root);
        var draw = Enumerable.Range(root.RootState.HandCount + 1, request.Cards.Where(card => card.Pile == "Draw")
            .Sum(card => card.Count)).Select(id => (ushort)id);
        var belief = DrawBelief.Create([], draw, []);
        var start = session.Open(root.RootState, root.RootCold, belief, stableIds, true);
        var world = session.Open(root.RootState, root.RootCold, belief, stableIds, true, keepWorldOrder: true);

        return fixture switch
        {
            "draws" => CheckDraws(session, root, start, stableIds),
            "nested" => CheckNested(session, root, start, world, loop, combat),
            "exhaust" => CheckExhaust(session, start),
            "shuffle" => CheckShuffle(session, root, start, world, loop, combat),
            "shuffle_multi" => CheckMultishuffle(session, start),
            "turn" => CheckTurn(session, root, start, world, loop, combat),
            "order" => CheckOrder(session, root, start, world, stableIds),
            "known" => CheckKnown(session, root, start, world, stableIds),
            "energy" => CheckSearch(session, start, world, 3, .5, 1),
            "plain" => CheckPlain(session, start, world, loop, combat),
            "pair" => CheckSearch(session, start, world, 48, 1, 1),
            "unsupported" => CheckUnsupported(session, start),
            "no_draw" => CheckNoDraw(session, start),
            "empty" => CheckNoDraw(session, start),
            "perfect_fit" => CheckPerfectFit(session, start),
            _ => throw new ArgumentException($"Unknown fixture: {fixture}")
        };
    }

    // The synthetic recipe is the provenance. Its explicit injections assign IDs before
    // treating any positions as unknown. This is not an importer for arbitrary live roots.
    private static Dictionary<ushort, ushort> BindFixtureInstances(UnattendedTestRequest request, HotRootBundle root)
    {
        CombatHotState state = root.RootState;
        var mapping = new Dictionary<ushort, ushort>();
        ushort next = 1;
        foreach (HotPileKind zone in Enum.GetValues<HotPileKind>())
        {
            var authored = request.Cards.Where(card => card.Pile == zone.ToString())
                .SelectMany(card => Enumerable.Repeat(card, card.Count)).ToArray();
            Check(authored.Length == HotPiles.ZoneCount(in state, zone), $"Fixture recipe and {zone} disagree.");
            int start = HotPiles.ZoneStart(in state, zone);
            for (int i = 0; i < authored.Length; i++)
            {
                ref readonly HotCard injected = ref state.Cards[start + i];
                Check(root.Rules.Cards[injected.CardDefId].Entry == authored[i].CardId
                    && injected.UpgradeLevel == authored[i].UpgradeLevels, $"Fixture card order mismatch at {zone}/{i}.");
                mapping.Add(injected.CardUid, next++);
            }
        }
        return mapping;
    }

    private static ushort[] CardIds(in CombatHotState state, int start, int length)
    {
        var ids = new ushort[length];
        for (int i = 0; i < length; i++)
            ids[i] = state.Cards[start + i].CardUid;
        return ids;
    }

    private static bool Victory(Snapshot state) => state.State.TerminalOutcome == HotCombatOutcome.Victory;

    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }

    private static void Equal(double actual, double expected, string name)
        => Check(Math.Abs(actual - expected) < 1e-12, $"{name}: expected {expected}, got {actual}");

    private static HotAction Play(Session session, Snapshot state, string card)
        => session.Actions(state, false).First(action => session.ActionName(state, action).StartsWith(card + "#"));

    private static Transition Status(Transition step, StepStatus expected)
    {
        Check(step.Status == expected, $"Expected {expected}, got {step.Status} ({step.Point}: {step.Reason}).");
        Check((step.Child != null) == (expected == StepStatus.Completed), "Partial state escaped replay.");
        return step;
    }

    private static string Events(Transition step) => JsonSerializer.Serialize(step.Events, Json);

    private static void Exact(Snapshot first, Snapshot second)
    {
        CombatHotState a = first.State, b = second.State;
        HotColdSidecar? ca = first.Cold, cb = second.Cold;
        byte[] bytesA = new byte[HotLimits.MaxPackedStateBytes];
        byte[] bytesB = new byte[HotLimits.MaxPackedStateBytes];
        int sizeA = HotStatePacker.Pack(ref a, ref ca, bytesA, canonicalize: false);
        int sizeB = HotStatePacker.Pack(ref b, ref cb, bytesB, canonicalize: false);
        Check(HotHash.PackedEquals(bytesA.AsSpan(0, sizeA), ca, bytesB.AsSpan(0, sizeB), cb),
            "Full hot state or Cold diverged.");
    }

    private static object CheckDraws(Session session, HotRootBundle root, Snapshot start,
        Dictionary<ushort, ushort> ids)
    {
        var action = Play(session, start, "POMMEL_STRIKE");
        var first = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        var options = first.Pending.Options;
        Check(options.Length == 3 && options.All(option => option.Denominator == 3), "Single draw support.");
        Check(options.Select(option => option.Observation).Distinct().Count() == 2,
            "Equivalent draws must share a public continuation.");
        double strike = options.Where(option => IsInstance(root, option.Instance, "STRIKE_IRONCLAD"))
            .Sum(option => option.Probability);
        Equal(strike, 2.0 / 3, "duplicate strike mass");
        Equal(1 - strike, 1.0 / 3, "defend mass");

        var paths = new List<object>();
        double mass = 0;
        foreach (var a in options)
        {
            var pa = Prefix.Empty.AddDraw(first.Pending, a.Instance);
            var second = Status(session.Advance(start, action, pa), StepStatus.NeedsChance);
            Check(second.Pending.Options.Length == 2 && second.Pending.Options.All(b => b.Instance != a.Instance),
                "Draw without replacement.");
            foreach (var b in second.Pending.Options)
            {
                var final = Status(session.Advance(start, action, pa.AddDraw(second.Pending, b.Instance)),
                    StepStatus.Completed);
                Check(final.Child!.State.HistoryCardsDrawn == start.State.HistoryCardsDrawn + 2,
                    "Two draws must settle exactly once.");
                Check(final.Child.State.Energy == start.State.Energy - 1 && final.Child.State.PlayCount == 0,
                    "Pommel payment or Play pile was committed incorrectly.");
                double probability = a.Probability * b.Probability;
                Equal(probability, 1.0 / 6, "ordered draw path");
                mass += probability;
                paths.Add(new { a.Instance, second = b.Instance, probability, final.Events });
            }
        }
        Check(paths.Count == 6, "All six paths are required.");
        Equal(mass, 1, "total draw mass");
        var wrong = Prefix.Empty.AddDraw(first.Pending with { Position = first.Pending.Position + 1 }, options[0].Instance);
        Status(session.Advance(start, action, wrong), StepStatus.Error);
        Status(session.Advance(start, action, Prefix.Empty.AddDraw(first.Pending, 600)), StepStatus.Error);

        CombatHotState variant = root.RootState;
        int variantIndex = variant.DrawStart;
        variant.Cards[variantIndex].EnergyCostMods[0] = new HotEnergyCostMod { Amount = -1 };
        variant.Cards[variantIndex].CostModCount = 1;
        variant.Cards[variantIndex].Var0Delta = 2;
        var changed = session.Open(in variant, root.RootCold, start.Belief, ids, true);
        Check(session.PublicKey(start) != session.PublicKey(changed), "Public cost and dynamic changes were erased.");
        var changedEvent = Status(session.Advance(changed, action, Prefix.Empty), StepStatus.NeedsChance);
        Check(changedEvent.Pending.Options.Length == 3, "Distinct variants were merged.");
        Check(changedEvent.Pending.Options.Select(option => option.Observation).Distinct().Count() == 3,
            "Different costs and variables must remain distinct observations.");

        var topBottom = DrawBelief.Create([options[0].Instance], [options[1].Instance], [options[2].Instance]);
        var constrained = session.Open(root.RootState, root.RootCold, topBottom, ids, true);
        var known = Status(session.Advance(constrained, action, Prefix.Empty), StepStatus.Completed);
        Check(known.Events.Select(entry => entry.Result).SequenceEqual(new ushort?[] { options[0].Instance, options[1].Instance })
            && known.Child!.Belief.Bottom.SequenceEqual(new[] { options[2].Instance }), "Known top/bottom precedence.");
        var fullState = start.State;
        fullState.MaxHandSize = 1;
        var full = Status(session.Advance(new Snapshot(in fullState, start.Cold, start.Belief), action, Prefix.Empty),
            StepStatus.Completed);
        Check(full.Events.Length == 0 && full.Child!.State.DrawCount == 3, "Full hand must not request or consume a draw.");
        var terminalState = start.State;
        terminalState.Enemies[0].Vital.CurrentHp = 1;
        var early = Status(session.Advance(new Snapshot(in terminalState, start.Cold, start.Belief), action, Prefix.Empty),
            StepStatus.Completed);
        Check(early.Outcome == HotCombatOutcome.Victory && early.Events.Length == 0, "Lethal should stop before drawing.");
        try
        {
            session.Open(root.RootState, root.RootCold, topBottom, ids, exchangeable: false);
            throw new InvalidOperationException("Nonexchangeable import did not stop.");
        }
        catch (Boundary boundary) when (boundary.Status == StepStatus.Unsupported)
        {
            Check(boundary.Message == "non_exchangeable_constraints", "Incorrect import diagnostic.");
        }
        ushort[] expectedPair = options.Take(2).Select(option => option.Instance).ToArray();
        bool JointGoal(Snapshot state)
        {
            ushort[] hand = CardIds(in state.State, 0, state.State.HandCount);
            return expectedPair.All(hand.Contains);
        }
        var budget = new Budget(400, 1, 2);
        var nosl = new Search(session, Mode.Nosl, budget, JointGoal).Run(start);
        var ideal = new Search(session, Mode.Ideal, budget, JointGoal).Run(start);
        Equal(nosl.Best.Mass.Success, 1.0 / 3, "two-draw joint target");
        Equal(nosl.Best.Mass.Upper, 1.0 / 3, "two-draw joint target upper bound");
        Equal(ideal.Best.Mass.Success, 1, "ideal two-draw joint target");
        return new { strike, defend = 1 - strike, paths, mass, known = known.Events, distinctModifiers = true,
            rejectsNonExchangeable = true, rejectsBadPrefix = true, fullHand = true, earlyTerminal = true,
            jointGoal = new { budget, nosl, ideal }, performance = Measure(session, start, root, action) };
    }

    private static bool IsInstance(HotRootBundle root, ushort uid, string entry)
    {
        for (int i = 0; i < root.RootState.TotalCardCount; i++)
        {
            HotCard card = root.RootState.Cards[i];
            if (card.CardUid == uid)
                return root.Rules.Cards[card.CardDefId].Entry == entry;
        }
        return false;
    }

    private static object CheckNested(Session session, HotRootBundle root, Snapshot start, Snapshot world,
        MainLoopContext loop, MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var action = Play(session, start, "PREPARED");
        var first = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        ushort statusCard = first.Pending.Options[0].Instance;
        Prefix withVoid = Prefix.Empty.AddDraw(first.Pending, statusCard);
        var nested = Status(session.Advance(start, action, withVoid), StepStatus.NeedsChance);
        Check(nested.Pending.DrawDepth == 2, "Iteration must draw recursively inside AfterCardDrawn.");
        var prefix = withVoid.AddDraw(nested.Pending, nested.Pending.Options[0].Instance);
        var choice = Status(session.Advance(start, action, prefix), StepStatus.NeedsChoice);
        Check(choice.Pending.Kind == EventKind.PlayerChoice && choice.Pending.Observation == "player_prompt"
            && choice.Pending.Choices.Length == 3, "The real discard prompt must follow both draws.");
        var chosen = prefix.AddChoice(choice.Pending, choice.Pending.Choices[0]);
        var a = Status(session.Advance(start, action, chosen), StepStatus.Completed);
        var b = Status(session.Advance(start, action, prefix.AddChoice(choice.Pending, choice.Pending.Choices[^1])),
            StepStatus.Completed);
        var aAgain = Status(session.Advance(start, action, chosen), StepStatus.Completed);
        Exact(a.Child!, aAgain.Child!);
        Check(Events(a) == Events(aAgain) && Events(a) != Events(b), "A/B/A replay differs.");
        var bAgain = Status(session.Advance(start, action, prefix.AddChoice(choice.Pending, choice.Pending.Choices[^1])),
            StepStatus.Completed);
        Exact(b.Child!, bAgain.Child!);
        Check(a.Child!.State.Energy == start.State.Energy - 1 && a.Child.State.HistoryCardsDrawn == start.State.HistoryCardsDrawn + 2,
            "Void energy or draw trigger was duplicated.");
        Status(session.Advance(start, action, prefix.AddChoice(choice.Pending, new PlayerOption(HotChoiceKind.HandCard, 800))),
            StepStatus.Error);
        Status(session.Advance(start, action, chosen.AddChoice(choice.Pending with { Position = choice.Pending.Position + 1 }, choice.Pending.Choices[0])),
            StepStatus.Error);
        return new { first = first.Pending, nested = nested.Pending, choice = choice.Pending, committed = a.Events,
            reverseOrder = true, staleRejected = true, excessRejected = true,
            audit = CompareNative(session, root, world, action, loop, combat, "DEFEND_IRONCLAD") };
    }

    private static object CheckExhaust(Session session, Snapshot start)
    {
        var action = Play(session, start, "BURNING_PACT");
        var choice = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChoice);
        var prefix = Prefix.Empty.AddChoice(choice.Pending, choice.Pending.Choices[0]);
        var steps = new List<StepEvent>();
        var done = Resolve(session, start, action, prefix, steps);
        Check(done.Child!.State.ExhaustCount == start.State.ExhaustCount + 1 &&
            done.Child.State.HistoryCardsDrawn == start.State.HistoryCardsDrawn + 3,
            "Burning Pact and Dark Embrace did not settle exactly once.");
        return new { done.Events, exhausted = done.Child.State.ExhaustCount, drawn = 3 };
    }

    private static object CheckMultishuffle(Session session, Snapshot start)
    {
        var action = Play(session, start, "POMMEL_STRIKE");
        var first = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        Check(first.Events[0].Kind == EventKind.Shuffle && first.Pending.Options.Length == 3, "Unexpected shuffle support.");
        int paths = 0;
        double total = 0;
        foreach (var a in first.Pending.Options)
        {
            Prefix prefix = Prefix.Empty.AddDraw(first.Pending, a.Instance);
            var second = Status(session.Advance(start, action, prefix), StepStatus.NeedsChance);
            foreach (var b in second.Pending.Options)
            {
                var child = Status(session.Advance(start, action, prefix.AddDraw(second.Pending, b.Instance)),
                    StepStatus.Completed).Child!;
                Check(a.Instance != b.Instance && child.Belief.Unknown.Length == 1 &&
                    child.State.ShuffleEventCount == 1, "Multishuffle instance or event conservation error.");
                Equal(a.Probability * b.Probability, 1.0 / 6, "shuffle ordered path probability");
                paths++;
                total += a.Probability * b.Probability;
            }
        }
        Check(paths == 6, "Missing shuffle histories.");
        Equal(total, 1, "shuffle path mass");
        return new { paths, total };
    }

    private static Transition Resolve(Session session, Snapshot start, HotAction action, Prefix prefix,
        List<StepEvent>? boundaries = null)
    {
        for (int attempt = 0; attempt < 32; attempt++)
        {
            var step = session.Advance(start, action, prefix);
            if (step.Status == StepStatus.Completed)
                return step;
            Check(step.Status is StepStatus.NeedsChoice or StepStatus.NeedsChance,
                $"Unexpected {step.Status} at {step.Point}: {step.Reason}");
            var e = step.Pending;
            boundaries?.Add(e);
            prefix = step.Status == StepStatus.NeedsChoice ? prefix.AddChoice(e, e.Choices[0])
                : prefix.AddDraw(e, e.Options[0].Instance);
        }
        throw new InvalidOperationException("Fixture exceeded action event replay limit.");
    }

    private static Prefix Script(Transition observed) => new(
        observed.Events.Where(entry => entry.Kind == EventKind.Draw)
            .Select(entry => new DrawInput(entry.Address, entry.Result!.Value)).ToArray(),
        observed.Events.Where(entry => entry.Kind == EventKind.PlayerChoice)
            .Select(entry => new ChoiceInput(entry.Address, entry.Selection!)).ToArray());

    private static object CheckShuffle(Session session, HotRootBundle root, Snapshot start, Snapshot world,
        MainLoopContext loop, MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var action = Play(session, start, "SHRUG_IT_OFF");
        var pending = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        Check(pending.Events[0].Kind == EventKind.Shuffle && pending.Pending.Options.Length == 3,
            "Ordinary shuffle must expose three conditional draws.");
        Equal(pending.Pending.Options.Sum(item => item.Probability), 1, "shuffle probability");
        foreach (var option in pending.Pending.Options)
        {
            var child = Status(session.Advance(start, action, Prefix.Empty.AddDraw(pending.Pending, option.Instance)),
                StepStatus.Completed).Child!;
            Check(child.Belief.Generation == 1 && child.Belief.Unknown.Length == 2 && child.State.DiscardCount == 1,
                "Post-shuffle instance bookkeeping or Play timing is wrong.");
            Check(child.State.Player.Block == start.State.Player.Block + 14 && child.State.ShuffleEventCount == 1,
                "Abacus and Shrug must each resolve once.");
        }
        var audit = CompareNative(session, root, world, action, loop, combat);
        return new { conditionalChoices = pending.Events, audit };
    }

    private static object CheckTurn(Session session, HotRootBundle root, Snapshot start, Snapshot world,
        MainLoopContext loop, MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var action = HotAction.EndTurn();
        var trace = new List<StepEvent>();
        var step = Resolve(session, start, action, Prefix.Empty, trace);
        Check(step.Child!.State.PlayerTurnNumber == start.State.PlayerTurnNumber + 1 &&
            step.Events.Count(entry => entry.Phase == "turn_start_draw") == 5, "Turn-start draw sequence wrong.");
        return new { trace, audit = CompareNative(session, root, world, action, loop, combat) };
    }

    private static object CompareNative(Session session, HotRootBundle root, Snapshot world, HotAction action,
        MainLoopContext loop, MegaCrit.Sts2.Core.Combat.CombatState combat, string? discard = null)
    {
        Prefix prefix = Prefix.Empty;
        HotChoiceSelection[] originalChoices = [];
        string[] expectedPrompt = [];
        if (discard != null)
        {
            var paused = Status(session.Advance(world, action, prefix, Resolution.CaptureWorld), StepStatus.NeedsChoice);
            var chosen = paused.Pending.Choices.Single(option => IsInstance(root, option.Instance, discard));
            expectedPrompt = paused.Pending.Choices.Select(option => root.Rules.Cards[FindDef(world, option.Instance)].Entry).ToArray();
            prefix = prefix.AddChoice(paused.Pending, chosen);
            originalChoices = [new HotChoiceSelection(chosen.Kind, chosen.Instance, FindDef(world, chosen.Instance))];
        }
        var captured = Status(session.Advance(world, action, prefix, Resolution.CaptureWorld), StepStatus.Completed);
        var replay = Status(session.Advance(world, action, Script(captured), Resolution.ReplayWorld), StepStatus.Completed);
        Exact(captured.Child!, replay.Child!);
        Check(Events(captured) == Events(replay), "Fixed-world record/replay event mismatch.");
        CombatHotState plain = world.State;
        HotColdSidecar? cold = world.Cold;
        var ordinary = HotCombatEngine.Step(ref plain, ref cold, root.Rules, new HotExecScratch(), action, originalChoices);
        Check(ordinary.Executed && !ordinary.NeedsChoice, "Uninstrumented Oracle Step failed.");
        Exact(captured.Child!, new Snapshot(in plain, cold, captured.Child!.Belief));

        var player = LocalContext.GetMe(combat)!;
        RealCombatAction nativeAction = action.Kind == HotActionKind.EndTurn ? RealCombatAction.EndTurn()
            : RealCombatAction.PlayCard(player.PlayerCombatState!.Hand.Cards[action.SlotOrHandIdx],
                action.TargetEnemySlot < 0 ? null : combat.Enemies[action.TargetEnemySlot]);
        var selector = discard == null ? null : new NativeChoice(discard, expectedPrompt);
        using var scope = selector == null ? null : RunManager.Instance.CardSelectorStack.PushSelector(player, selector);
        var nativeOutcome = RealCombatDriver.RunRealCombatAction(loop, combat, nativeAction, TimeSpan.FromSeconds(10),
            () => selector?.Error);
        Check(selector == null || selector.Calls == 1, "Native choice was not requested exactly once.");
        Check(nativeOutcome == ordinary.Outcome, "Native outcome disagrees.");
        HotRootBundle native = HotRootBuilder.BuildFromLive(combat);
        string predicted = AuditFrame(root.Rules, in plain, cold);
        string observed = AuditFrame(native.Rules, native.RootState, native.RootCold);
        Check(predicted == observed, $"Native audit frame differs.\nExpected {predicted}\nActual {observed}");
        var ids = CardIds(in world.State, 0, world.State.TotalCardCount).ToDictionary(id => id);
        var publicRoot = session.Open(in world.State, world.Cold, world.Belief, ids, true);
        var publicReplay = Status(session.Advance(publicRoot, action, Script(captured)), StepStatus.Completed);
        Check(session.PublicKey(publicReplay.Child!) == session.PublicKey(captured.Child!), "Public audit replay differs.");
        int[] rngDeltas = new int[HotLimits.MaxRngStreams];
        for (int i = 0; i < rngDeltas.Length; i++)
            rngDeltas[i] = plain.Rng[i].Counter - world.State.Rng[i].Counter;
        Check(rngDeltas[(int)HotRngStream.Shuffle] == captured.LogicalShuffles, "Logical shuffle consumption differs.");
        return new { matched = true, captured.Events, captured.LogicalShuffles, rngDeltas,
            checkedNativeChoice = selector?.Calls, observedEnergy = native.RootState.Energy,
            observedHp = native.RootState.Player.CurrentHp, observedBlock = native.RootState.Player.Block };
    }

    private static ushort FindDef(Snapshot root, ushort instance)
    {
        for (int i = 0; i < root.State.TotalCardCount; i++)
        {
            ref readonly HotCard card = ref root.State.Cards[i];
            if (card.CardUid == instance)
                return card.CardDefId;
        }
        throw new InvalidOperationException("Choice instance is absent from the root.");
    }

    private sealed class NativeChoice(string card, string[] expected) : ICardSelector
    {
        public int Calls { get; private set; }
        public Exception? Error { get; private set; }

        public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
        {
            var menu = options.ToArray();
            Calls++;
            if (Calls != 1 || minSelect != 1 || maxSelect != 1 || !menu.Select(item => item.Id.Entry).SequenceEqual(expected))
            {
                Error = new InvalidOperationException($"Native choice menu differs. Actual: {string.Join(',', menu.Select(item => item.Id.Entry))}; expected: {string.Join(',', expected)}");
                throw Error;
            }
            return Task.FromResult<IEnumerable<CardModel>>([menu.Single(item => item.Id.Entry == card)]);
        }

        public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,
            IReadOnlyList<CardRewardAlternative> alternatives)
            => throw new InvalidOperationException("Unexpected native reward choice.");
    }

    private static string AuditFrame(HotRules rules, in CombatHotState state, HotColdSidecar? cold)
    {
        var cards = new List<string>();
        for (int i = 0; i < state.TotalCardCount; i++)
            cards.Add($"{HotPiles.PileOfIndex(in state, i)}:{HotContinuationStamp.FormatChoiceCardKey(in state.Cards[i], cold, rules)}");
        var rng = new List<ulong[]>();
        for (int i = 0; i < HotLimits.MaxRngStreams; i++)
        {
            var value = state.Rng[i];
            rng.Add([(ulong)value.Counter, value.S0, value.S1, value.S2, value.S3]);
        }
        var powers = new List<string>();
        for (int i = 0; i < state.PowerCount; i++)
        {
            var p = state.Powers[i];
            powers.Add($"{rules.Powers[p.PowerDefId].Entry}/{p.OwnerSlot}/{p.Amount}/{p.Aux0}");
        }
        var enemy = state.Enemies[0];
        string? move = rules.GetMonsterMachine(enemy.MonsterDefId)?.Nodes[enemy.CurrentMoveNode].MoveId;
        return JsonSerializer.Serialize(new { hp = state.Player.CurrentHp, state.Player.Block, state.Energy, state.Stars,
            state.PlayerTurnNumber, state.HistoryCardsDrawn, state.HistoryFinishedPlays,
            enemyHp = enemy.Vital.CurrentHp, enemyBlock = enemy.Vital.Block, move, cards, powers, rng }, Json);
    }

    private static object CheckSearch(Session session, Snapshot start, Snapshot world, int horizon,
        double expectedNosl, double expectedIdeal)
    {
        var budget = new Budget(20_000, horizon, 12);
        var nosl = new Search(session, Mode.Nosl, budget, Victory).Run(start);
        var ideal = new Search(session, Mode.Ideal, budget, Victory).Run(start);
        var oracle = new Search(session, Mode.Oracle, budget, Victory).Run(world);
        Equal(nosl.Best.Mass.Success, expectedNosl, "NOSL value");
        Equal(nosl.Best.Mass.Upper, expectedNosl, "NOSL upper");
        Equal(ideal.Best.Mass.Success, expectedIdeal, "Ideal value");
        Equal(ideal.Best.Mass.Upper, expectedIdeal, "Ideal upper");
        return new { budget, nosl, ideal, oracle };
    }

    private static object CheckPlain(Session session, Snapshot start, Snapshot world, MainLoopContext loop,
        MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var results = CheckSearch(session, start, world, 1, 1, 1);
        var player = LocalContext.GetMe(combat)!;
        var native = RealCombatAction.PlayCard(player.PlayerCombatState!.Hand.Cards.Single(), combat.Enemies.Single());
        var outcome = RealCombatDriver.RunRealCombatAction(loop, combat, native, TimeSpan.FromSeconds(10));
        Check(outcome == HotCombatOutcome.Victory, "Native deterministic lethal was not a victory.");
        return new { modes = results, nativeTerminal = outcome };
    }

    private static object CheckOrder(Session session, HotRootBundle root, Snapshot start, Snapshot world,
        Dictionary<ushort, ushort> ids)
    {
        CombatHotState other = root.RootState;
        (other.Cards[other.DrawStart], other.Cards[other.DrawStart + 1]) =
            (other.Cards[other.DrawStart + 1], other.Cards[other.DrawStart]);
        other.Rng[(int)HotRngStream.Shuffle] = HotRng.CreateFromSeed(678902UL);
        var otherIds = ids.ToDictionary(item => (ushort)(item.Key + 100), item => item.Value);
        for (int i = 0; i < other.TotalCardCount; i++)
            other.Cards[i].CardUid += 100;
        var paired = session.Open(in other, root.RootCold, start.Belief, otherIds, true);
        Check(session.PublicKey(start) == session.PublicKey(paired), "Public root sees private order, UID or RNG.");
        var action = Play(session, start, "FLASH_OF_STEEL");
        string parent = session.PublicKey(start);
        var paused = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        Check(Events(paused) == Events(Status(session.Advance(paired, action, Prefix.Empty), StepStatus.NeedsChance)),
            "Public support depends on private implementation.");
        var branches = new Dictionary<ushort, Transition>();
        foreach (var outcome in paused.Pending.Options)
        {
            var prefix = Prefix.Empty.AddDraw(paused.Pending, outcome.Instance);
            var a = Status(session.Advance(start, action, prefix), StepStatus.Completed);
            var b = Status(session.Advance(paired, action, prefix), StepStatus.Completed);
            Check(Events(a) == Events(b) && session.PublicKey(a.Child!) == session.PublicKey(b.Child!) &&
                session.Actions(a.Child!, true).SequenceEqual(session.Actions(b.Child!, true)), "Public successor leak.");
            branches.Add(outcome.Instance, a);
        }
        foreach (var outcome in paused.Pending.Options.Reverse())
        {
            var step = Status(session.Advance(start, action, Prefix.Empty.AddDraw(paused.Pending, outcome.Instance)),
                StepStatus.Completed);
            Exact(branches[outcome.Instance].Child!, step.Child!);
            Check(Events(branches[outcome.Instance]) == Events(step), "Reverse-order replay differs.");
        }
        var budget = new Budget(500, 2, 3);
        foreach (var mode in new[] { Mode.Nosl, Mode.Ideal })
        {
            var a = new Search(session, mode, budget, Victory).Run(start);
            var b = new Search(session, mode, budget, Victory).Run(paired);
            Check(JsonSerializer.Serialize(new { a.Best, a.RootActions }, Json) ==
                JsonSerializer.Serialize(new { b.Best, b.RootActions }, Json), "Public search leak.");
        }
        Check(session.PublicKey(start) == parent, "Replay mutated parent snapshot.");
        var firstKnown = session.Open(root.RootState, root.RootCold,
            DrawBelief.Create([start.Belief.Unknown[0]], [start.Belief.Unknown[1]], []), ids, true);
        var secondKnown = session.Open(in other, root.RootCold,
            DrawBelief.Create([start.Belief.Unknown[1]], [start.Belief.Unknown[0]], []), otherIds, true);
        Check(session.PublicKey(firstKnown) != session.PublicKey(secondKnown), "Public top negative control missing.");
        var cutoff = new Search(session, Mode.Nosl, new Budget(500, 2, 0), Victory).Run(start);
        Equal(cutoff.Best.Mass.Unresolved, 1, "event budget unresolved mass");
        Equal(cutoff.Best.Mass.Upper, 1, "event budget upper bound");

        var win = new Value(Mass.Win, []);
        var lose = new Value(Mass.Loss, null);
        var unknown = new Value(Mass.Unknown, null);
        var before = Search.Best([Search.Expectation([(.5, win), (.5, lose)]),
            Search.Expectation([(.5, lose), (.5, win)])]);
        var after = Search.Expectation([(.5, Search.Best([win, lose])), (.5, Search.Best([lose, win]))]);
        var unresolved = Search.Expectation([(.5, win), (.25, lose), (.25, unknown)]);
        Equal(before.Mass.Success, .5, "decision before the reveal");
        Equal(after.Mass.Success, 1, "decision after the reveal");
        Equal(unresolved.Mass.Success, .5, "truncated lower bound");
        Equal(unresolved.Mass.Upper, .75, "truncated upper bound");

        var frozenPolicy = branches.Values.Sum(branch =>
            session.Actions(branch.Child!, false).Any(candidate =>
                session.ActionName(branch.Child!, candidate).StartsWith("STRIKE_IRONCLAD#")) ? .5 : 0);
        Equal(frozenPolicy, .5, "legal post-observation policy");
        var mixed = new Search(session, Mode.Ideal, budget, Victory, _ => false).Run(start);
        Equal(mixed.Best.Mass.Success, .5, "non-idealized event retains probability");
        return new { publicPair = true, negativeControl = true, pending = paused.Pending, cutoff = cutoff.Best.Mass,
            handTrees = new { before = before.Mass, after = after.Mass, truncated = unresolved.Mass }, frozenPolicy,
            modes = CheckSearch(session, start, world, 2, .5, 1) };
    }

    private static object CheckKnown(Session session, HotRootBundle root, Snapshot start, Snapshot world,
        Dictionary<ushort, ushort> ids)
    {
        var set = Resolve(session, start, Play(session, start, "HEADBUTT"), Prefix.Empty);
        Check(set.Child!.Belief.Top.Length == 1 && IsInstance(root, set.Child.Belief.Top[0], "STRIKE_IRONCLAD"),
            "Headbutt did not create a known top.");
        var next = Status(session.Advance(set.Child, Play(session, set.Child, "FLASH_OF_STEEL"), Prefix.Empty),
            StepStatus.Completed);
        Check(next.Events.Single().Kind == EventKind.KnownDraw &&
            next.Events.Single().Result == set.Child.Belief.Top[0], "Known top was bypassed.");
        return new { top = set.Child.Belief.Top, next.Events, modes = CheckSearch(session, start, world, 3, 1, 1) };
    }

    private static object CheckNoDraw(Session session, Snapshot start)
    {
        var action = Play(session, start, "SHRUG_IT_OFF");
        var done = Status(session.Advance(start, action, Prefix.Empty), StepStatus.Completed);
        Check(done.Events.Length == 0 && done.Child!.State.HandCount == 0, "No Draw emitted a chance or drew a card.");
        return new { blockedDraw = true, done.Child!.State.DrawCount };
    }

    private static object CheckUnsupported(Session session, Snapshot start)
    {
        var havoc = Status(session.Advance(start, Play(session, start, "HAVOC"), Prefix.Empty), StepStatus.Unsupported);
        var draw = Status(session.Advance(start, Play(session, start, "SHRUG_IT_OFF"), Prefix.Empty), StepStatus.NeedsChance);
        var forced = Status(session.Advance(start, Play(session, start, "SHRUG_IT_OFF"),
            Prefix.Empty.AddDraw(draw.Pending, draw.Pending.Options[0].Instance)), StepStatus.Unsupported);
        Check(havoc.Reason == "autoplay_from_draw" && forced.Reason == "unmodeled_rng", "Unsupported reason was lost.");
        return new { autoplay = new { havoc.Reason, havoc.Point }, randomCost = new { forced.Reason, forced.Point } };
    }

    private static object CheckPerfectFit(Session session, Snapshot start)
    {
        var result = Status(session.Advance(start, Play(session, start, "SHRUG_IT_OFF"), Prefix.Empty), StepStatus.Unsupported);
        Check(result.Reason == "perfect_fit", "Shuffle order modifier was not rejected at the shuffle.");
        return new { result.Reason, result.Point };
    }

    private static object Measure(Session session, Snapshot start, HotRootBundle root, HotAction action)
    {
        const int count = 500;
        var first = Status(session.Advance(start, action, Prefix.Empty), StepStatus.NeedsChance);
        var p1 = Prefix.Empty.AddDraw(first.Pending, first.Pending.Options[0].Instance);
        var second = Status(session.Advance(start, action, p1), StepStatus.NeedsChance);
        var p2 = p1.AddDraw(second.Pending, second.Pending.Options[0].Instance);
        var single = Play(session, start, "FLASH_OF_STEEL");
        var singleEvent = Status(session.Advance(start, single, Prefix.Empty), StepStatus.NeedsChance).Pending;
        var singlePrefix = Prefix.Empty.AddDraw(singleEvent, singleEvent.Options[0].Instance);
        for (int i = 0; i < 100; i++)
        {
            Status(session.Advance(start, action, p2), StepStatus.Completed);
            Status(session.Advance(start, single, singlePrefix), StepStatus.Completed);
        }
        long belief = 0;
        double timedResearch = Timing(() => belief += session.Advance(start, action, p2).BeliefTicks);
        double timedSingle = Timing(() => _ = session.Advance(start, single, singlePrefix));
        var scratch = new HotExecScratch();
        double timedFixed = Timing(() =>
        {
            CombatHotState state = root.RootState;
            HotColdSidecar? cold = root.RootCold;
            _ = HotCombatEngine.Step(ref state, ref cold, root.Rules, scratch, action);
        });
        double singleFanout = Timing(() =>
        {
            var boundary = session.Advance(start, single, Prefix.Empty).Pending;
            foreach (var option in boundary.Options)
                _ = session.Advance(start, single, Prefix.Empty.AddDraw(boundary, option.Instance));
        });
        double doubleFanout = Timing(() =>
        {
            var boundary = session.Advance(start, action, Prefix.Empty).Pending;
            foreach (var option in boundary.Options)
            {
                var prefix = Prefix.Empty.AddDraw(boundary, option.Instance);
                var next = session.Advance(start, action, prefix).Pending;
                foreach (var branch in next.Options)
                    _ = session.Advance(start, action, prefix.AddDraw(next, branch.Instance));
            }
        });
        int sink = 0;
        double copy = Timing(() => sink += CopyState(in start.State));
        return new { iterations = count, warmupIterations = 100, fixedStepUs = timedFixed,
            researchOneDrawStepUs = timedSingle, researchTwoDrawStepUs = timedResearch,
            singleFanoutUs = singleFanout, doubleFanoutUs = doubleFanout, copyUs = copy, copySink = sink,
            beliefUs = belief * 1_000_000.0 / Stopwatch.Frequency / count };

        static double Timing(Action run)
        {
            long began = Stopwatch.GetTimestamp();
            for (int i = 0; i < count; i++)
                run();
            return (Stopwatch.GetTimestamp() - began) * 1_000_000.0 / Stopwatch.Frequency / count;
        }
    }

    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static int CopyState(in CombatHotState state)
    {
        CombatHotState copy = state;
        return ReadState(in copy);
    }

    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static int ReadState(in CombatHotState state) => state.HandCount + state.Cards[0].CardUid;
}
