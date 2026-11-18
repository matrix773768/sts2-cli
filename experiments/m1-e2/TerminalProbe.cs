using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Rooms;

namespace OfflineSearchHarness;

internal sealed partial class RouteProbe
{
    private static RouteProbe? _active;
    private int _action;
    private Phase? _lastBefore;
    private Phase? _initial;
    private bool? _rawTerminalEqual;
    private string? _alignment;
    private CardModel[] _taintedAtVictory = [];
    private readonly List<int> _vitalSparkRemovalActions = [];
    private static readonly Regex TurnHistory = new(@";Y=\d+/\d+/\d+/\d+;FlameHp=\d+;AttackStarts=\d+");
    private PlanAction? _reference;
    private readonly List<Phase> _phases = [];
    private sealed record Phase(int Action, string Stage, JsonNode State, bool InProgress, int Hp, int Gold,
        int MaxHp, string[] Deck, string?[] Potions, string[] Relics, int Round, string Side, int HistorySize, int PlayStartCount, int DrawCount, int RetainedTainted, string[] PlayerEvents);

    internal IDisposable InstallLifecycle()
    {
        var patch = new Harmony("sts2.m1-e2.lifecycle");
        _active = this;
        foreach (string name in new[] { "EndCombatInternal", "ProcessPendingLoss" })
        {
            var method = typeof(CombatManager).GetMethods(BindingFlags.Instance | BindingFlags.NonPublic)
                .Single(m => m.Name == name && m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
            patch.Patch(method, prefix: new HarmonyMethod(AccessTools(nameof(TerminalPrefix), typeof(RouteProbe))));
        }
        var afterRemoved = typeof(VitalSparkPower).GetMethod("AfterRemoved",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            ?? throw new MissingMethodException(nameof(VitalSparkPower), "AfterRemoved");
        patch.Patch(afterRemoved, prefix: new HarmonyMethod(AccessTools(nameof(VitalSparkRemoved), typeof(RouteProbe))));
        CombatManager.Instance.CombatEnded += CombatEnded;
        return new Lifecycle(patch, this);
    }

    private sealed class Lifecycle(Harmony patch, RouteProbe owner) : IDisposable
    {
        public void Dispose()
        {
            CombatManager.Instance.CombatEnded -= owner.CombatEnded;
            patch.UnpatchAll(patch.Id);
            _active = null;
        }
    }

    private static void VitalSparkRemoved()
    {
        if (_active is { } route)
            route._vitalSparkRemovalActions.Add(route._action);
    }

    private static void TerminalPrefix(MethodBase __originalMethod)
    {
        if (_active is not { } route)
            return;
        if (__originalMethod.Name == "EndCombatInternal")
            route._taintedAtVictory = route._player.PlayerCombatState!.AllCards
                .Where(c => c.Affliction?.Id.Entry == "TAINTED").ToArray();
        route.CapturePhase(__originalMethod.Name);
    }
    private void CombatEnded(CombatRoom room)
    {
        if (ReferenceEquals(room, _combat.RunState.CurrentRoom))
            CapturePhase("combat_ended_event");
    }

    private void CapturePhase(string stage) => _phases.Add(Observe(stage));

    private Phase Observe(string stage)
    {
        var history = CombatManager.Instance.History;
        return new(_action, stage, Native(), CombatManager.Instance.IsInProgress,
            _player.Creature.CurrentHp, _player.Gold, _player.Creature.MaxHp,
            _player.Deck.Cards.Select(c => CardChoiceSupport.ChoiceCardKey(c)).ToArray(),
            _player.PotionSlots.Select(p => p?.Id.Entry).ToArray(),
            _player.Relics.Select(r => r.Id.Entry).ToArray(), _combat.RoundNumber, _combat.CurrentSide.ToString(),
            history.Entries.Count(), history.CardPlaysStarted.Count(),
            history.Entries.Count(e => e.GetType().Name == "CardDrawnEntry"),
            _taintedAtVictory.Count(c => c.Affliction?.Id.Entry == "TAINTED"),
            history.Entries.Where(e => e.GetType().Name is "CardDrawnEntry" or "CardPlayStartedEntry")
                .TakeLast(12).Select(e => e + " | current=" + e.HappenedThisTurn(_combat)).ToArray());
    }

    internal void BeforeAction(int action)
    {
        _action = action;
        if (action == 1)
            _initial = Observe("before_first_action");
        if (action == Inputs.Length)
            _lastBefore = Observe("before_last_action");
        if (action == 19 && Environment.GetEnvironmentVariable("M1E2_BRANCH") == "1")
        {
            var card = _player.PlayerCombatState!.Hand.Cards.Single(c => c.Id.Entry == "FRANTIC_ESCAPE");
            _reference = new(PlanActionKind.PlayCard, _player.PlayerCombatState.TurnNumber,
                CardId: card.Id.Entry, CardStateKey: CardChoiceSupport.ChoiceCardKey(card));
        }
    }

    private JsonNode ObserveActionReturn(int index)
    {
        if (_state.TerminalStamp == null && _phases.Count == 0)
            return Native();
        CapturePhase("action_queue_return");
        var boundary = _phases.FirstOrDefault(p => p.Action == index
            && p.Stage is "ProcessPendingLoss" or "EndCombatInternal");
        if (boundary is null)
            return _nativeTerminal ?? _phases[^1].State;
        var shadow = Shadow(_state);
        var raw = boundary.State;
        _rawTerminalEqual = JsonNode.DeepEquals(shadow, raw);
        if (_rawTerminalEqual == false && boundary.Stage == "ProcessPendingLoss"
            && _lastBefore is { Side: "Player" } before && boundary.Side == "Enemy"
            && boundary.Round == before.Round && _state.TerminalStamp?.PlayerTurn == before.Round
            && boundary.PlayStartCount == before.PlayStartCount && boundary.DrawCount == before.DrawCount)
        {
            // The action did not add a play or draw. Compare the shadow's last player window
            // with the independently recorded native player-window values.
            var projection = raw.DeepClone();
            for (int i = 0; i < _enemies.Length; i++)
            {
                string oldText = raw[i]!["exactContinuationState"]!.GetValue<string>();
                string priorText = before.State[i]!["exactContinuationState"]!.GetValue<string>();
                var oldHistory = TurnHistory.Matches(oldText);
                var priorHistory = TurnHistory.Matches(priorText);
                if (oldHistory.Count != 1 || priorHistory.Count != 1)
                    return raw;
                const string zeroPrefix = ";Y=0/0/0/0";
                if (!oldHistory[0].Value.StartsWith(zeroPrefix, StringComparison.Ordinal)
                    || !oldHistory[0].Value.EndsWith(";AttackStarts=0", StringComparison.Ordinal)
                    || oldHistory[0].Value.Split(';')[2] != priorHistory[0].Value.Split(';')[2])
                    return raw;
                projection[i]!["exactContinuationState"] = TurnHistory.Replace(oldText, priorHistory[0].Value, 1);
            }
            if (JsonNode.DeepEquals(shadow, projection))
            {
                _alignment = "last_player_window";
                return projection;
            }
        }
        return raw;
    }

    private void FinishTerminal(string status, bool aligned)
    {
        var predicted = Shadow(_state);
        var end = _phases.LastOrDefault(p => p.Stage == "action_queue_return");
        var callback = _phases.SingleOrDefault(p => p.Stage == "combat_ended_event");
        bool resourcesStable = _initial is { } start && end is not null
            && end.Gold == start.Gold && end.MaxHp == start.MaxHp && end.Deck.SequenceEqual(start.Deck)
            && end.Relics.SequenceEqual(start.Relics) && end.Potions.SequenceEqual(start.Potions);
        var lossBoundary = _phases.SingleOrDefault(p => p.Stage == "ProcessPendingLoss");
        bool lossCompletion = lossBoundary is not null && callback is not null
            && end is { InProgress: false } && !callback.InProgress
            && JsonNode.DeepEquals(lossBoundary.State, callback.State)
            && JsonNode.DeepEquals(callback.State, end.State);
        bool semantic = aligned && lossCompletion && end is not null
            && resourcesStable && end.Hp == predicted[0]!["playerHp"]!.GetValue<int>()
            && _state.TerminalStamp?.PlayerTurn == end.Round
            && Enumerable.Range(0, _enemies.Length).All(i => JsonNode.DeepEquals(
                end.State[i]!["enemyHp"], predicted[i]!["enemyHp"]))
            && JsonNode.DeepEquals(end.State[0]!["rngCounters"], predicted[0]!["rngCounters"]);
        File.WriteAllText(Path.Combine(_output, "terminal.json"), JsonSerializer.Serialize(new
        {
            status, aligned, semantic, lossCompletion, resourcesStable, rawTerminalEqual = _rawTerminalEqual,
            alignment = _alignment, vitalSparkRemovalActions = _vitalSparkRemovalActions, terminalStamp = _state.TerminalStamp?.ToString(),
            lastBefore = _lastBefore, phases = _phases, predicted, branch = BranchBatches(),
        }, Json));
    }

    private object? BranchBatches()
    {
        if (_reference == null || _matched < 18 || _plan.Count != 19)
            return null;
        long parentStart = Stopwatch.GetTimestamp();
        var parent = Step(_solver, null, null);
        try
        {
            foreach (var action in _plan.Take(18))
            {
                var next = Step(_solver, parent, action);
                parent.ReleaseSimulator();
                parent = next;
            }
            double parentMs = Elapsed(parentStart);
            var alternative = _plan[18];
            var expected = Digest(Shadow(_state));
            string parentHash = Digest(Shadow(parent));
            var first = BranchStep(parent, _reference);
            var alternate = BranchStep(parent, alternative);
            var repeated = BranchStep(parent, _reference);
            if (alternate.Digest != expected || first.Digest != repeated.Digest || first.Digest == alternate.Digest)
                throw new InvalidOperationException("Alternative replay differs from native-verified child");
            var forkSamples = new List<object>();
            for (int i = 0; i < 7; i++)
            {
                long bytes = GC.GetAllocatedBytesForCurrentThread();
                long start = Stopwatch.GetTimestamp();
                var fork = ((CombatPredictionSimulator)parent.Simulator).Fork();
                forkSamples.Add(new { ms = Elapsed(start), bytes = GC.GetAllocatedBytesForCurrentThread() - bytes });
                GC.KeepAlive(fork);
            }
            var samples = new List<object>();
            foreach (int count in new[] { 2, 4, 8 })
            {
                for (int repeat = 0; repeat < 7; repeat++)
                {
                    long bytes = GC.GetAllocatedBytesForCurrentThread();
                    long start = Stopwatch.GetTimestamp();
                    for (int i = 0; i < count; i++)
                        Step(_solver, parent, i % 2 == 0 || (_matched != 19) ? _reference : alternative).ReleaseSimulator();
                    samples.Add(new { count, ms = Elapsed(start), bytes = GC.GetAllocatedBytesForCurrentThread() - bytes });
                }
            }
            if (BranchStep(parent, alternative).Digest != expected || parentHash != Digest(Shadow(parent)))
                throw new InvalidOperationException("Batched branch polluted the parent");
            return new { lifecycleNativeAlternative = _matched == 19, strictNativeAlternative = _matched == 19 && _rawTerminalEqual != false,
                includesAlternative = _matched == 19, first, alternate, repeated,
                parentHash, parentMs, forkSamples, samples };
        }
        finally { parent.ReleaseSimulator(); }
    }
}
