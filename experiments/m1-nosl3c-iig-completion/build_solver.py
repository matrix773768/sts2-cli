"""Build the completion branch without changing the frozen II-G executable."""
from hashlib import sha256
import json
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIG = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig/build_solver.py"))
edit = IIG["edit"]
VERSION = "0.51.5-iig.2"


def diagnose(source):
    search = source / "Search"
    sim = source / "Engine/InCombat/Simulation"
    continuation = sim / "CombatPredictionSimulator.ExecutionContinuation.cs"
    checkpoints = search / "CombatBeamSolver.ExecutionChoiceContinuation.cs"
    bridge = search / "CombatBeamSolver.InteractiveCombat.cs"
    history = sim / "CombatPredictionHistory.ExecutionContinuation.cs"

    edit(continuation, "    private bool _executionContinuationRejected;",
         """    private bool _executionContinuationRejected;
    internal string? ExecutionCaptureFailure { get; set; }
    internal string? ExecutionCheckpointFailure { get; set; }""")
    edit(continuation, "        if (!StateStore.SupportsManualCardChoiceContinuation) return false;",
         """        if (StateStore.ExecutionContinuationBlocker is { } blocker)
        {
            ExecutionCaptureFailure = "capture_store:" + blocker;
            return false;
        }""")
    store = source / "Engine/Common/PredictionStateStore.CardContinuation.cs"
    edit(store, "    internal bool SupportsManualCardChoiceContinuation",
         """    internal string? ExecutionContinuationBlocker => _states?.Values
        .FirstOrDefault(state => state.GetType().Assembly != typeof(PredictionStateStore).Assembly
            || state is IPredictionForkBoundary)?.GetType().FullName;

    internal bool SupportsManualCardChoiceContinuation""")
    reset = """        _executionContinuationRejected = false;
        ExecutionCaptureFailure = null;
        ExecutionCheckpointFailure = null;
"""
    for next_line in ("        _pendingExecutionSteps = null;",
                      "        _executionContinuationHistoryStart = continuation.HistoryStart;"):
        edit(continuation, "        _executionContinuationRejected = false;\n" + next_line,
             reset + next_line)
    edit(continuation, """        RejectExecutionContinuation();
        return null;
    }

    internal void RejectExecutionContinuation()
    {
        if (_captureExecutionContinuation) _executionContinuationRejected = true;
    }""", """        RejectExecutionContinuation("capture_scopes:" + frame.GetType().Name);
        return null;
    }

    internal void RejectExecutionContinuation(
        [System.Runtime.CompilerServices.CallerMemberName] string member = "",
        [System.Runtime.CompilerServices.CallerLineNumber] int line = 0)
    {
        if (!_captureExecutionContinuation) return;
        _executionContinuationRejected = true;
        ExecutionCaptureFailure ??= member + ":" + line;
    }""")
    edit(continuation, """        if (_executionContinuationRejected || steps is not { Count: > 0 }
            || State.CombatState is not ICombatPredictionExecutionContinuationState { CanCaptureExecutionContinuation: true }
            || !StateStore.SupportsManualCardChoiceContinuation
            || !History.SupportsExecutionContinuation(_executionContinuationHistoryStart,
                steps.SelectMany(step => step.Frame.DeferredEntries),
                steps.SelectMany(step => step.Frame.ActiveCardPlays)))
            return null;""", """        ExecutionCheckpointFailure = _executionContinuationRejected ? "rejected"
            : steps is not { Count: > 0 } ? "no_execution_steps"
            : State.CombatState is not ICombatPredictionExecutionContinuationState { CanCaptureExecutionContinuation: true }
                ? "state_not_quiescent"
            : !StateStore.SupportsManualCardChoiceContinuation ? "state_store"
            : History.ExecutionContinuationBlocker(_executionContinuationHistoryStart,
                steps.SelectMany(step => step.Frame.DeferredEntries),
                steps.SelectMany(step => step.Frame.ActiveCardPlays));
        if (ExecutionCheckpointFailure is not null) return null;""")
    edit(continuation, "        _ownedExecutionContinuation = new(_executionContinuationHistoryStart, steps);",
         "        _ownedExecutionContinuation = new(_executionContinuationHistoryStart, steps!);")
    edit(history, "    internal bool SupportsExecutionContinuation(", "    internal string? ExecutionContinuationBlocker(")
    edit(history, "        if ((_prefix?.Count ?? 0) != start) return false;",
         '        if ((_prefix?.Count ?? 0) != start) return "history_prefix";')
    edit(history, "                default: return false;", '                default: return "history_entry:" + entry.GetType().Name;')
    edit(history, """        return unresolved.Count == _pendingDeferredEntries && unresolved.SetEquals(deferred)
            && active.SetEquals(activePlays);""", """        if (unresolved.Count != _pendingDeferredEntries || !unresolved.SetEquals(deferred))
            return "history_deferred_entries";
        return active.SetEquals(activePlays) ? null : "history_active_plays";""")
    edit(checkpoints, "        if (tail is null) return null;", """        if (tail is null)
        {
            simulator.ExecutionCheckpointFailure = "no_replay_tail";
            return null;
        }""")
    edit(checkpoints, "        if (tail.ConsumedChoices != prefix.Count) return null;", """        if (tail.ConsumedChoices != prefix.Count)
        {
            simulator.ExecutionCheckpointFailure = $"choice_prefix:{tail.ConsumedChoices}/{prefix.Count}";
            return null;
        }""")
    edit(bridge, "                boundary = Current.BoundaryReason.ToString(), action = _plan,", """                boundary = Current.BoundaryReason.ToString(), action = _plan,
                capture_failure = Current.Simulator.ExecutionCaptureFailure,
                checkpoint_failure = Current.Simulator.ExecutionCheckpointFailure,
                risk_reasons = Current.Simulator.History.Entries.OfType<CombatPredictionRiskEntry>()
                    .Select(e => e.Reason.ToString()).Distinct().ToArray(),""")
    edit(bridge, "            if (next.BoundaryReason != SearchBoundaryReason.PendingChoice) return;",
         """            if (next.BoundaryReason != SearchBoundaryReason.PendingChoice)
            {
                TraceInteraction("solver_boundary", null, false);
                return;
            }""")
    edit(bridge, "                LastCompletedAction = _plan;",
         """                if (next.HasRisk) TraceInteraction("solver_risk", null, false);
                LastCompletedAction = _plan;""")


def draw_reveal(source):
    search = source / "Search"
    choice = search / "CardChoiceSupport.cs"
    bridge = search / "CombatBeamSolver.InteractiveCombat.cs"
    start = source / "Prediction/TurnStartChoiceSupport.cs"
    power = source / "Prediction/TurnStartPowerSupport.cs"
    edit(choice, "    internal bool PublicReveal { get; init; }",
         """    internal bool PublicReveal { get; init; }
    internal bool RandomizedReveal { get; init; }""")
    edit(choice, "contextId) { PublicReveal = true };",
         "contextId) { PublicReveal = true, RandomizedReveal = true };")
    edit(choice, """? revealed.OrderBy(card => card.Preview.Rarity).ThenBy(card => card,
                Comparer<PredictedCard>.Create((a, b) => CombatCardOrdering.Compare(simulator, a, b))).ToList()""",
         "? OrderRevealedDrawCards(simulator, revealed)")
    edit(choice, "            Cleanse => Spec(owner, PlanChoiceEffect.Exhaust, PileType.Draw, 1, owner.DrawPile.Cards),",
         """            Cleanse => RevealDrawChoice(simulator,
                Spec(owner, PlanChoiceEffect.Exhaust, PileType.Draw, 1, owner.DrawPile.Cards)),""")
    edit(choice, "    private static CardChoiceSpec? BuildSeekerSpec(",
         """    private static List<PredictedCard> OrderRevealedDrawCards(CombatPredictionSimulator simulator,
        IEnumerable<PredictedCard> cards)
        => cards.OrderBy(card => card.Preview.Rarity).ThenBy(card => card,
            Comparer<PredictedCard>.Create((a, b) => CombatCardOrdering.Compare(simulator, a, b))).ToList();

    // Only call from native FromCombatPile requests with a reviewed visible candidate set.
    internal static CardChoiceSpec? RevealDrawChoice(CombatPredictionSimulator simulator, CardChoiceSpec? spec)
        => !PublishingInteractiveChoices || spec == null ? spec : spec with
        {
            Options = OrderRevealedDrawCards(simulator, spec.Options),
            PublicReveal = true,
        };

    private static CardChoiceSpec? BuildSeekerSpec(""")
    edit(bridge, "            if (spec.SourcePile == PileType.Draw && spec.Options.Any(option =>",
         "            if (spec.RandomizedReveal && spec.Options.Any(option =>")
    edit(start, "        PileType sourcePile = PileType.Hand)",
         "        PileType sourcePile = PileType.Hand, bool revealDrawPile = false)")
    edit(start, """            IsImplicitAllSelection: options.Count <= requestedCount);
        TurnStartChoiceRequest request = new(""", """            IsImplicitAllSelection: options.Count <= requestedCount);
        if (revealDrawPile)
            spec = CardChoiceSupport.RevealDrawChoice(simulator, spec)!;
        TurnStartChoiceRequest request = new(""")
    edit(power, """                        power.Amount,
                        PileType.Draw))""", """                        power.Amount,
                        PileType.Draw, revealDrawPile: true))""")


def replay_fallback(source):
    bridge = source / "Search/CombatBeamSolver.InteractiveCombat.cs"
    action_choices = source / "Search/SimulatedCombatState.ActionChoices.cs"
    edit(action_choices, """            ReplacementValue: 0d);
        TurnStartChoiceRequest request = new(
            string.Empty,""", """            ReplacementValue: 0d,
            IsImplicitAllSelection: CardChoiceSupport.PublishingInteractiveChoices);
        TurnStartChoiceRequest request = new(
            string.Empty,""")
    edit(action_choices, """            if (!HasPendingChoice)
                SetPendingTurnStartChoice(request);
            return false;""", """            if (!HasPendingChoice)
            {
                SetPendingTurnStartChoice(request);
                if (CardChoiceSupport.PublishingInteractiveChoices)
                    simulator.CaptureExecutionChoice(new CardSelectionExecutionFrame(card, request));
            }
            return false;""")
    edit(bridge, "        private SimulationSnapshot? _current = seed;", """        private SimulationSnapshot? _current = seed;
        // Retained only for the in-flight action. Each replay forks this same stable state.
        private SimulationSnapshot? _replayOrigin;
        private bool _replayWaiting;""")
    edit(bridge, "            _startTurn = Current.Turn;", """            _replayOrigin = Current;
            _startTurn = Current.Turn;""")
    edit(bridge, """            var checkpoint = _checkpoint!;
            Install(solver.ResumeExecutionChoice(checkpoint, null, _plan));""", """            if (_checkpoint is { } checkpoint)
                Install(solver.ResumeExecutionChoice(checkpoint, null, _plan));
            else if (_replayWaiting)
                Install(ReplayChoice());
            else
                throw new InvalidOperationException("The pending interaction lost its owner.");""")
    edit(bridge, "            if (!ReferenceEquals(Current, seed)) Current.ReleaseSimulator();",
         "            if (!ReferenceEquals(Current, seed) && !ReferenceEquals(Current, _replayOrigin)) Current.ReleaseSimulator();")
    edit(bridge, "            _checkpoint = null;\n            _request = null;\n            InteractionTrace = null;",
         "            _checkpoint = null;\n            _request = null;\n            _replayWaiting = false;\n            InteractionTrace = null;")
    edit(bridge, "                if (next.HasRisk) TraceInteraction", """                ReleaseReplayOrigin();
                if (next.HasRisk) TraceInteraction""")
    edit(bridge, """            TraceInteraction(_checkpoint != null ? "published" : "checkpoint_unavailable", pending, _checkpoint != null);
            if (_checkpoint != null) _request = pending;""", """            if (_checkpoint != null)
            {
                TraceInteraction("published", pending, true);
                _request = pending;
                return;
            }
            if (!next.HasRisk && _replayOrigin != null && EquivalentFullReplay(next))
            {
                TraceInteraction("published_by_replay", pending, false);
                _replayWaiting = true;
                _request = pending;
                return;
            }
            TraceInteraction("checkpoint_unavailable", pending, false);""")
    edit(bridge, "        public void Dispose()", """        private SimulationSnapshot ReplayChoice()
        {
            var origin = _replayOrigin ?? throw new InvalidOperationException("Missing stable replay origin.");
            var next = solver.Replay([_plan!], origin, origin.Turn);
            try
            {
                if (!EquivalentFullReplay(next))
                    throw new NotSupportedException("Deterministic choice replay diverged after submit.");
                return next;
            }
            catch
            {
                next.ReleaseSimulator();
                throw;
            }
        }

        private bool EquivalentFullReplay(SimulationSnapshot expected)
        {
            var origin = _replayOrigin!;
            var twin = solver.Replay([_plan!], origin, origin.Turn, allowExecutionCapture: false);
            try
            {
                return expected.BoundaryReason == twin.BoundaryReason
                    && expected.Turn == twin.Turn
                    && expected.HasRisk == twin.HasRisk
                    && expected.ProcessedEnemyDeaths.Order().SequenceEqual(twin.ProcessedEnemyDeaths.Order())
                    && solver.CaptureDiagnosticContinuation(expected) == solver.CaptureDiagnosticContinuation(twin)
                    && expected.Simulator.History.Entries.Select(e => e.GetType())
                        .SequenceEqual(twin.Simulator.History.Entries.Select(e => e.GetType()))
                    && SamePendingBinding(expected, twin);
            }
            finally { twin.ReleaseSimulator(); }
        }

        private static bool SamePendingBinding(SimulationSnapshot a, SimulationSnapshot b)
        {
            static TurnStartChoiceRequest? Pending(SimulationSnapshot snapshot)
                => ((SimulatedCombatState)snapshot.Simulator.State.CombatState).PendingTurnStartChoice;
            static IEnumerable<(string Key, int SourceIndex)> Identities(CardChoiceSpec spec)
            {
                var source = spec.SourceCards.ToList();
                return spec.Options.Select(card => (CardChoiceSupport.ChoiceCardKey(card),
                    source.FindIndex(c => ReferenceEquals(c.Original, card.Original))));
            }
            var left = Pending(a);
            var right = Pending(b);
            if (left == null || right == null) return left == right;
            return left is { Spec: { } x } && right is { Spec: { } y }
                && left.SourceId == right.SourceId && left.ContextId == right.ContextId
                && left.Timing == right.Timing && left.Effect == right.Effect && left.SourcePile == right.SourcePile
                && left.Count == right.Count && x.MinCount == y.MinCount && x.MaxCount == y.MaxCount
                && x.PublicReveal == y.PublicReveal && x.IsImplicitAllSelection == y.IsImplicitAllSelection
                && Identities(x).SequenceEqual(Identities(y));
        }

        private void ReleaseReplayOrigin()
        {
            if (_replayOrigin is { } origin && !ReferenceEquals(origin, seed) && !ReferenceEquals(origin, _current))
                origin.ReleaseSimulator();
            _replayOrigin = null;
        }

        public void Dispose()""")
    edit(bridge, "            _checkpoint = null;\n            if (_current",
         "            _checkpoint = null;\n            ReleaseReplayOrigin();\n            if (_current")


def power_application(source):
    # Native PowerCmd.Apply exits once CombatManager.IsEnding, including when
    # called after a lethal attack inside a larger autoplay.
    file = source / "Prediction/CardEffectSpecRegistry.cs"
    edit(file, """                int amount = effect.Amount(card);
                Creature owner = ownerCreature;""", """                if (simulator.IsEnding) break;
                int amount = effect.Amount(card);
                Creature owner = ownerCreature;""")
    powers = source / "Search/SimulatedCombatState.cs"
    edit(powers, """    public void ApplyAnticipate(Creature creature, int amount, Creature? applier)
    {
        int before = GetAmount<AnticipatePower>(creature);
        Apply<AnticipatePower>(creature, amount, applier);
        int applied = GetAmount<AnticipatePower>(creature) - before;
        if (applied <= 0)
            return;
        Apply<DexterityPower>(creature, applied, applier);
    }""", """    public void ApplyAnticipate(Creature creature, int amount, Creature? applier)
        => ApplyTemporaryDexterity<AnticipatePower>(creature, amount, applier);""")


def stage(command, **kwargs):
    # II-G applies its original changes first. Then the last build layer applies
    # these changes before invoking the compiler.
    iid_stage = IIG["IID"]["stage"]

    def compile_staged(args, **options):
        source = Path(args[2]).parent / "src"
        diagnose(source)
        draw_reveal(source)
        replay_fallback(source)
        power_application(source)
        iid_stage(args, **options)
        manifest = {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest()
                    for p in source.rglob("*.cs")}
        output = Path(args[-1]).parent
        (output / "completion-sources.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")

    upstream = IIG["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ | {"IID": {"stage": compile_staged}})(
        command, **kwargs)


if __name__ == "__main__":
    f = IIG["BASE"]["main"]
    FunctionType(f.__code__, f.__globals__ | dict(VERSION=VERSION, subprocess=SimpleNamespace(run=stage)))()
