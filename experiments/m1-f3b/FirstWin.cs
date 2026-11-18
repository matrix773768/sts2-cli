using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin : IDisposable
{
    private const int ActionLimit = 48;
    private const int WallMs = 12_000;
    private const long MemoryLimit = 448L * 1024 * 1024;
    private static readonly IntentForecast EmptyForecast = new()
    {
        Rounds = [], HasUnsupportedIntent = false, IsExactForModeledDamage = true,
        UnsupportedDetails = [], ApproximationDetails = [], MonsterAiCountersByRound = [],
    };

    private sealed record Option(PlanAction Action, RealCombat.Move? Card);
    private sealed record EnemyState(uint? Id, int Hp, int Block);
    private sealed record Frame(string Stamp, int Turn, int Hp, int Block, int Energy,
        EnemyState[] Enemies, string[] Hand, string[] Draw, string[] Discard, string[] Exhaust,
        string[] Powers, string?[] Potions, int CumulativeLoss, string Stop, string Boundary,
        bool Risk, string[] Gaps)
    {
        public int Remaining => Enemies.Sum(e => e.Hp);
        public int Alive => Enemies.Count(e => e.Hp > 0);
    }
    private sealed class Node(int id, Node? parent, Option? option, SimulationSnapshot snapshot, Frame frame)
    {
        public int Id { get; } = id;
        public Node? Parent { get; } = parent;
        public Option? Option { get; } = option;
        public int Depth { get; } = (parent?.Depth ?? -1) + 1;
        public Frame Frame { get; } = frame;
        public SimulationSnapshot? State { get; set; } = snapshot;
        public PublicState? View { get; set; }
        public Option[]? Options { get; set; }
    }

    private readonly Player _player;
    private readonly Node _root;
    private readonly Func<SimulationSnapshot, PlanAction, SimulationSnapshot> _advance;
    private readonly int _cap;
    private readonly bool _potions;
    private readonly HashSet<string> _rejected;
    private readonly Process _process = Process.GetCurrentProcess();
    private readonly HashSet<Node> _live = [];
    private readonly List<object> _history = [];
    private readonly List<object> _checkpoints = [];
    private readonly List<object> _transitionFaults = [];
    private readonly Stopwatch _watch = new();
    private int _used, _reused, _branches, _diagnoses, _rejectedWins, _memoryPeak;
    private string? _limit;
    private string? _detail;
    private Node? _winner;
    private double _replayMs, _auditMs, _observeMs;

    internal FirstWin(Player player, SimulationSnapshot seed,
        Func<SimulationSnapshot, PlanAction, SimulationSnapshot> advance, int cap,
        bool potions, HashSet<string> rejected)
    {
        _player = player;
        _advance = advance;
        _cap = cap;
        _potions = potions;
        _rejected = rejected;
        try
        {
            _root = Record(null, null, seed);
            if (_root.Frame.Stop != "active")
                throw new NotSupportedException($"Root is not an active stable boundary: {_root.Frame.Boundary}");
        }
        catch
        {
            seed.ReleaseSimulator();
            _process.Dispose();
            throw;
        }
    }

    private static string Hash(string text) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();

    private Node Record(Node? parent, Option? option, SimulationSnapshot snapshot)
    {
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var pc = sim.State.GetPlayerCombatState(_player);
        var combat = (SimulatedCombatState)sim.State.CombatState;
        string digest = Digest(snapshot);
        string stop = snapshot.HasRisk || snapshot.BoundaryReason != SearchBoundaryReason.None ? "unsupported" :
            snapshot.TerminalStamp == null ? "active" : snapshot.PlayerDead ? "death" :
            snapshot.AllEnemiesDead ? "predicted_win" : "unsupported";
        string[] Pile(IEnumerable<PredictedCard> pile) =>
            pile.Select(c => $"{c.Preview.Id.Entry}+{c.Preview.CurrentUpgradeLevel}").ToArray();
        var frame = new Frame(digest, snapshot.Turn, snapshot.PlayerHp, snapshot.PlayerBlock, snapshot.Energy,
            combat.KnownEnemies.Select(e =>
            {
                var enemy = sim.State.GetCreature(e);
                return new EnemyState(e.CombatId, enemy.CurrentHp, enemy.Block);
            }).ToArray(), Pile(pc.Hand.Cards), Pile(pc.DrawPile.Cards), Pile(pc.DiscardPile.Cards),
            Pile(pc.ExhaustPile.Cards), combat.EffectivePowers().Select(p =>
                $"{p.Owner.CombatId}:{p.Id.Entry}:{p.Amount}").Order().ToArray(),
            Enumerable.Range(0, _player.PotionSlots.Count)
                .Select(i => combat.GetPotionAtSlot(_player, i)?.Id.Entry).ToArray(),
            snapshot.CumulativePlayerHpLost, stop, snapshot.BoundaryReason.ToString(), snapshot.HasRisk,
            snapshot.PredictionGaps.Select(g => g.Key + ": " + g.Reason).ToArray());
        var node = new Node(_history.Count, parent, option, snapshot, frame);
        _live.Add(node);
        _history.Add(new { id = node.Id, parent = parent?.Id, action = option?.Action, frame });
        return node;
    }

    private string Digest(SimulationSnapshot snapshot) =>
        Hash(ContinuationStamp.CapturePredicted(_player, (CombatPredictionSimulator)snapshot.Simulator,
            snapshot.Turn, EmptyForecast, snapshot.Turn).StateText);

    private bool Continue()
    {
        if (_limit != null) return false;
        if (_used >= _cap) _limit = "transition_cap";
        else if (_watch.ElapsedMilliseconds >= WallMs) _limit = "wall_cap";
        else if (_used % 32 == 0)
        {
            _process.Refresh();
            long memory = _process.PeakWorkingSet64;
            _memoryPeak = Math.Max(_memoryPeak, (int)Math.Min(memory, int.MaxValue));
            if (memory > MemoryLimit) _limit = "memory_cap";
        }
        return _limit == null;
    }

    private Node? Advance(Node parent, Option option)
    {
        if (!Continue()) return null;
        if (parent.Frame.Stop != "active" || parent.State is not { } snapshot)
            throw new InvalidOperationException("Attempted to fork an unavailable prediction boundary");
        ((CombatPredictionSimulator)snapshot.Simulator).AssertForkable();
        _used++;
        long started = Stopwatch.GetTimestamp();
        SimulationSnapshot next;
        try { next = _advance(snapshot, option.Action); }
        catch (TargetInvocationException error) when
            (error.InnerException is PredictionUnsupportedException or NotSupportedException)
        {
            _transitionFaults.Add(new { transition = _used, parent = parent.Id, option.Action,
                detail = error.InnerException!.Message });
            throw new NotSupportedException(error.InnerException.Message);
        }
        finally { _replayMs += Stopwatch.GetElapsedTime(started).TotalMilliseconds; }
        started = Stopwatch.GetTimestamp();
        try
        {
            var child = Record(parent, option, next);
            if (_used is 128 or 512 or 2048)
                _checkpoints.Add(new { transitions = _used, hot_ms = _watch.Elapsed.TotalMilliseconds,
                    routes = _routes.Count, branches = _branches, reused = _reused, diagnoses = _diagnoses });
            return child;
        }
        catch
        {
            next.ReleaseSimulator();
            throw;
        }
        finally { _auditMs += Stopwatch.GetElapsedTime(started).TotalMilliseconds; }
    }

    private Option[] Menu(Node node)
    {
        if (node.Options != null) return node.Options;
        var snapshot = node.State!;
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var hand = sim.State.GetPlayerCombatState(_player).Hand.Cards;
        long started = Stopwatch.GetTimestamp();
        node.View = ObservePrediction(snapshot);
        var options = new List<Option>();
        foreach (var move in node.View.Menu.Moves)
        {
            var card = hand[move.HandIndex];
            var key = CardChoiceSupport.ChoiceCardKey(card);
            var before = hand.Take(move.HandIndex);
            PlanCardChoice? choice = null;
            if (move.Id is "HEADBUTT" or "SURVIVOR" &&
                CardChoiceSupport.GetSpec(sim, card) is { Options.Count: > 0 } spec)
                choice = SelectCard(spec, move.Id == "SURVIVOR" ? card : null);
            options.Add(new(new PlanAction(PlanActionKind.PlayCard, node.Frame.Turn,
                CardId: move.Id, CardOccurrence: before.Count(c => c.Preview.Id.Entry == move.Id),
                TargetCombatId: move.Target, Choice: choice, CardStateKey: key,
                CardStateOccurrence: before.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key)), move));
        }
        if (_potions)
        {
            for (int i = 0; i < _player.PotionSlots.Count; i++)
                if (combat.IsPotionAvailable(_player, i) && combat.GetPotionAtSlot(_player, i) is { } potion
                    && (potion.Id.Entry is "DEXTERITY_POTION" or "FLEX_POTION" or "BLESSING_OF_THE_FORGE")
                    && potion.TargetType == TargetType.AnyPlayer && potion.IsValidTarget(_player.Creature))
                    options.Add(new(new PlanAction(PlanActionKind.UsePotion, node.Frame.Turn,
                        PotionSlot: i, PotionId: potion.Id.Entry), null));
        }
        options.Add(new(new PlanAction(PlanActionKind.EndTurn, node.Frame.Turn), null));
        _observeMs += Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        return node.Options = options.ToArray();
    }

    private static PlanCardChoice? SelectCard(CardChoiceSpec spec, PredictedCard? played)
    {
        int Value(PredictedCard option)
        {
            var card = option.Preview;
            int Stat(string name) => card.DynamicVars.Values.Where(v => v.Name.Equals(name, StringComparison.OrdinalIgnoreCase))
                .Sum(v => (int)v.BaseValue);
            return card.Type is CardType.Status or CardType.Curse ? -10000 :
                3 * Stat("Damage") + 4 * Stat("Block") + 5 * card.CurrentUpgradeLevel
                - 3 * (card.EnergyCost?.GetResolved() ?? 0) + (card.Type == CardType.Power ? 15 : 0);
        }
        // A Survivor's callback sees the hand after the played instance has left it.
        // Both occurrence counters must be in that callback's coordinate system.
        var options = spec.Options;
        var source = spec.SourceCards;
        if (played != null)
        {
            if (spec is not { Effect: PlanChoiceEffect.Discard, SourcePile: PileType.Hand, MinCount: 1, MaxCount: 1 })
                return null;
            options = options.Where(c => !ReferenceEquals(c.Original, played.Original)).ToArray();
            source = source.Where(c => !ReferenceEquals(c.Original, played.Original)).ToArray();
        }
        if (options.Count == 0)
            return null;
        var picked = played == null ? options.OrderByDescending(Value).First() : options.OrderBy(Value).First();
        string key = CardChoiceSupport.ChoiceCardKey(picked);
        int Occurrence(IEnumerable<PredictedCard> cards) => cards.TakeWhile(c => !ReferenceEquals(c, picked))
            .Count(c => CardChoiceSupport.ChoiceCardKey(c) == key);
        var token = new PlanCardToken(picked.Preview.Id.Entry, picked.Preview.CurrentUpgradeLevel, key,
            Occurrence(source), Occurrence(options), picked.Preview.Title);
        return new(spec.Effect, spec.SourcePile, [token], ContextId: spec.ContextId);
    }

    private static List<Node> Path(Node node)
    {
        var path = new List<Node>();
        for (Node? item = node; item != null; item = item.Parent) path.Add(item);
        path.Reverse();
        return path;
    }

    private bool Win(Node node)
    {
        if (node.Frame.Stop != "predicted_win") return false;
        if (_rejected.Contains(RouteKey(node)))
        {
            _rejectedWins++;
            return false;
        }
        _winner = node;
        return true;
    }

    private static string RouteKey(Node node) =>
        Hash(JsonSerializer.Serialize(Path(node).Skip(1).Select(n => n.Option!.Action)));

    private void Release(Node node)
    {
        if (_live.Remove(node))
        {
            node.State!.ReleaseSimulator();
            node.State = null;
        }
    }

    private void Keep(IEnumerable<Node> retained)
    {
        var set = retained.ToHashSet();
        foreach (var node in _live.Where(n => !set.Contains(n)).ToArray()) Release(node);
    }

    internal object Run(string arm, JsonElement? repairProbe)
    {
        TimeSpan cpu = _process.TotalProcessorTime;
        _watch.Start();
        string rootBefore = _root.Frame.Stamp;
        try
        {
            if (repairProbe is { } fixture) ProbeRepair(fixture);
            else if (arm == "B") Beam();
            else Routes(arm);
        }
        catch (NotSupportedException error)
        {
            _detail = error.Message;
            _limit = "unsupported";
        }
        _watch.Stop();
        var rootAfter = Digest(_root.State!);
        if (rootAfter != rootBefore) throw new InvalidOperationException("Search mutated root");
        var path = _winner == null ? null : Path(_winner).Skip(1).ToArray();
        _process.Refresh();
        return new
        {
            status = _winner != null ? "predicted_win" : _limit ?? "exhausted",
            detail = _detail, cap = _cap, transitions = _used, reused_prefix_transitions = _reused,
            branches = _branches, diagnoses = _diagnoses, rejected_wins = _rejectedWins,
            hot_ms = _watch.Elapsed.TotalMilliseconds, cpu_ms = (_process.TotalProcessorTime - cpu).TotalMilliseconds,
            replay_ms = _replayMs, frame_audit_ms = _auditMs, menu_ms = _observeMs,
            peak_working_set_bytes = Math.Max(_process.PeakWorkingSet64, _memoryPeak),
            root_stamp = rootBefore, root_unchanged = true, checkpoints = _checkpoints,
            winner_key = _winner == null ? null : RouteKey(_winner), winner_node = _winner?.Id,
            actions = path?.Select(n => n.Option!.Action).ToArray(),
            stamps = path?.Select(n => n.Frame.Stamp).ToArray(), routes = _routes, history = _history,
            transition_faults = _transitionFaults,
        };
    }

    public void Dispose()
    {
        Keep([]);
        _process.Dispose();
    }
}
