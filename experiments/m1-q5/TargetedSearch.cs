using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Mirrors;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;

namespace OfflineSearchHarness;

internal sealed partial class RouteProbe
{
    private const int PrefixLength = 18;
    private const int ActionLimit = 8;

    private sealed record PublicState(FastCombat.Observation Menu, int Hp, int Energy, int? Sandpit,
        string[] Hand, string[] Powers, string[] EnemyPowers);
    private sealed record Decision(Input Input, PublicState Public, string? SuccessorHash = null);
    private sealed record Goal(string Name, string? First, bool EscapeNext = false);
    private sealed record Endpoint(int Turn, int Hp, int Block, int Energy, int Incoming, int EnemyHp,
        int? Sandpit, bool PlayerDead, bool AllEnemiesDead, double EscapeEnergy, int EscapePlays, string? SpecialRisk);
    private sealed record Candidate(string Name, List<Decision> Decisions, Endpoint Endpoint, string Stop,
        int Transitions, double AdvanceMs, double ObserveMs, double PolicyMs, double EvaluateMs, string? Detail);
    private static readonly Goal[] Goals =
    [
        new("escape_first", "FRANTIC_ESCAPE"),
        new("frozen_q1", null),
        new("end_now", "END_TURN"),
        new("block_first", "COMPACT"),
        new("draw_first", "SKIM"),
        new("power_first", "SPINNER"),
        new("attack_then_escape", "MOMENTUM_STRIKE", true),
        new("block_then_escape", "COMPACT", true),
    ];
    private readonly List<object> _publicChecks = [];
    private readonly HashSet<string> _statesSeen = [];
    private Decision[]? _expectedPublic;
    private readonly List<object> _successorChecks = [];

    private PublicState ReadNative(FastCombat.Observation menu)
    {
        var player = _player.PlayerCombatState!;
        return new(menu, _player.Creature.CurrentHp, player.Energy,
            _combat.Enemies.SelectMany(e => e.Powers).SingleOrDefault(p => p.Id.Entry == "SANDPIT_POWER")?.Amount,
            player.Hand.Cards.Select(c => $"{c.Id.Entry}+{c.CurrentUpgradeLevel}").ToArray(),
            _player.Creature.Powers.Select(p => $"{p.Id.Entry}:{p.Amount}").Order().ToArray(),
            _combat.Enemies.SelectMany(e => e.Powers.Select(p => $"{e.CombatId}:{p.Id.Entry}:{p.Amount}"))
                .Order().ToArray());
    }

    internal bool VerifyPublic(int index, FastCombat.Observation menu)
    {
        var path = Environment.GetEnvironmentVariable("M1Q5_EXPECTED");
        if (path == null || index < PrefixLength)
            return true;
        _expectedPublic ??= JsonSerializer.Deserialize<Decision[]>(File.ReadAllText(path), Json)!;
        var actual = JsonSerializer.SerializeToNode(ReadNative(menu), Json);
        var expected = JsonSerializer.SerializeToNode(_expectedPublic[index - PrefixLength].Public, Json);
        bool equal = JsonNode.DeepEquals(actual, expected);
        _publicChecks.Add(new { step = index + 1, equal, actual = equal ? null : actual, expected = equal ? null : expected });
        return equal;
    }

    internal bool VerifyGenerated(int index)
    {
        if (_expectedPublic == null || index < PrefixLength)
            return true;
        var expected = _expectedPublic[index - PrefixLength].SuccessorHash;
        bool equal = expected == _digest;
        _successorChecks.Add(new { step = index + 1, equal, expected, actual = _digest });
        if (!equal)
            _status = "generated_successor_difference";
        return equal;
    }

    private PublicState ObservePrediction(SimulationSnapshot snapshot)
    {
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var pc = sim.State.GetPlayerCombatState(_player);
        var hero = sim.State.GetCreature(_player.Creature);
        var targets = combat.Enemies.Where(sim.State.IsHittable).ToArray();
        var enemies = targets.Select(enemy =>
        {
            var state = sim.State.GetCreature(enemy);
            int damage = combat.CurrentMonsterMove(enemy).AttackHits.Sum(hit => (int)HookMirrors.ModifyDamage(
                sim, _player.Creature, enemy, hit.BaseDamage, ValueProp.Move, null, null));
            return new FastCombat.Enemy(enemy.CombatId, state.CurrentHp, state.Block, damage);
        }).ToArray();

        var moves = new List<FastCombat.Move>();
        for (int i = 0; i < pc.Hand.Cards.Count; i++)
        {
            var card = pc.Hand.Cards[i];
            if (!combat.CanPlayCard(sim, card))
                continue;
            var model = card.Preview;
            var targetType = sim.GetTargetType(card);
            if (targetType is not (TargetType.AnyEnemy or TargetType.Self or TargetType.None
                or TargetType.AllEnemies or TargetType.RandomEnemy))
                throw new NotSupportedException($"Target type: {targetType} ({model.Id.Entry})");
            var candidates = targetType == TargetType.AnyEnemy ? targets : new Creature?[] { null };
            foreach (var target in candidates)
            {
                decimal Value(string name) => model.DynamicVars.TryGetValue(name, out var value) ? value.BaseValue : 0;
                decimal damage = Value("Damage");
                if (model.DynamicVars.TryGetValue("CalculatedDamage", out var variable))
                {
                    if (variable is not CalculatedVar calculated
                        || !CalculatedVarSpecRegistry.TryCalculate(calculated, sim, card, target, out decimal result))
                        throw new NotSupportedException($"Calculated damage preview: {model.Id.Entry}");
                    damage = Math.Max(damage, result);
                }
                if (damage != 0)
                    damage = HookMirrors.ModifyDamage(sim, target, _player.Creature, damage,
                        variable is CalculatedDamageVar cv ? cv.Props
                            : model.DynamicVars.TryGetValue("Damage", out var dv) && dv is DamageVar typed
                                ? typed.Props : ValueProp.Move, card, null);
                decimal block = Value("Block");
                if (block != 0)
                    block = HookMirrors.ModifyBlock(sim, _player.Creature, block,
                        model.DynamicVars.Block.Props, card, null, out _);
                moves.Add(new(i, model.Id.Entry, target?.CombatId, (int)damage * Math.Max(1, (int)Value("Repeat")),
                    (int)block, (int)Value("Cards"), card.GetEnergyCostWithModifiers(sim, pc), model.Type == CardType.Power));
            }
        }
        var powers = combat.EffectivePowers().ToArray();
        return new(new(hero.Block, enemies, moves), hero.CurrentHp, pc.Energy,
            powers.SingleOrDefault(p => p.Id.Entry == "SANDPIT_POWER")?.Amount,
            pc.Hand.Cards.Select(c => $"{c.Preview.Id.Entry}+{c.Preview.CurrentUpgradeLevel}").ToArray(),
            powers.Where(p => ReferenceEquals(p.Owner, _player.Creature))
                .Select(p => $"{p.Id.Entry}:{p.Amount}").Order().ToArray(),
            powers.Where(p => targets.Contains(p.Owner)).Select(p => $"{p.Owner.CombatId}:{p.Id.Entry}:{p.Amount}")
                .Order().ToArray());
    }

    private PlanAction ToPlan(SimulationSnapshot state, FastCombat.Move? move)
    {
        if (move == null)
            return new(PlanActionKind.EndTurn, state.Turn);
        var hand = state.Simulator.State.GetPlayerCombatState(_player).Hand.Cards;
        var key = CardChoiceSupport.ChoiceCardKey(hand[move.HandIndex]);
        var leading = hand.Take(move.HandIndex);
        return new(PlanActionKind.PlayCard, state.Turn, CardId: move.Id,
            CardOccurrence: leading.Count(c => c.Preview.Id.Entry == move.Id), TargetCombatId: move.Target,
            CardStateKey: key, CardStateOccurrence: leading.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key));
    }

    private Candidate Rollout(Goal goal, bool audit)
    {
        var state = _state;
        var decisions = new List<Decision>();
        int transitions = 0, escapes = 0, energy = 0;
        double advance = 0, observe = 0, policy = 0, evaluate = 0;
        string stop = "action_cap";
        string? detail = null;
        string? specialRisk = null;
        PublicState? final = null;
        try
        {
            for (int i = 0; i < ActionLimit; i++)
            {
                long started = Stopwatch.GetTimestamp();
                var observed = ObservePrediction(state);
                observe += Elapsed(started);
                started = Stopwatch.GetTimestamp();
                string? target = i == 0 ? goal.First : i == 1 && goal.EscapeNext ? "FRANTIC_ESCAPE" : null;
                var move = target == null ? FastCombat.Decide(observed.Menu, tactical: true)
                    : target == "END_TURN" ? null : observed.Menu.Moves.FirstOrDefault(m => m.Id == target);
                if (target is not (null or "END_TURN") && move == null)
                {
                    stop = "required_action_unavailable";
                    break;
                }
                var action = ToPlan(state, move);
                policy += Elapsed(started);
                decisions.Add(new(new(state.Turn, move == null ? null : new(move.HandIndex, move.Id, move.Target), null), observed));
                started = Stopwatch.GetTimestamp();
                var next = Step(_solver, state, action);
                advance += Elapsed(started);
                transitions++;
                if (!ReferenceEquals(state, _state)) state.ReleaseSimulator();
                state = next;
                if (move?.Id == "FRANTIC_ESCAPE")
                {
                    escapes++;
                    energy += move.Energy;
                }
                if (audit)
                {
                    string hash = Digest(Shadow(state));
                    _statesSeen.Add(hash);
                    decisions[^1] = decisions[^1] with { SuccessorHash = hash };
                }
                if (next.HasRisk || next.BoundaryReason != SearchBoundaryReason.None)
                {
                    stop = "prediction_boundary";
                    detail = next.BoundaryReason + "/" + next.HasRisk;
                    break;
                }
                if (state.TerminalStamp != null)
                {
                    stop = state.PlayerDead ? "death" : "victory";
                    if (state.PlayerDead && move == null && observed.Sandpit == 1)
                        specialRisk = "sandpit_at_one_before_end_turn";
                    break;
                }
                if (state.Turn > _state.Turn)
                {
                    stop = "one_player_round";
                    break;
                }
            }
            long evaluationStart = Stopwatch.GetTimestamp();
            if (state.TerminalStamp == null && stop is "one_player_round" or "action_cap")
                final = ObservePrediction(state);
            var endpoint = ReadEndpoint(state, final, energy, escapes, specialRisk);
            evaluate += Elapsed(evaluationStart);
            return new(goal.Name, decisions, endpoint, stop, transitions, advance, observe, policy, evaluate, detail);
        }
        catch (NotSupportedException error)
        {
            return new(goal.Name, decisions, ReadEndpoint(state, null, energy, escapes, specialRisk),
                "unsupported_public_projection", transitions, advance, observe, policy, evaluate, error.Message);
        }
        finally
        {
            if (!ReferenceEquals(state, _state)) state.ReleaseSimulator();
        }
    }

    private Endpoint ReadEndpoint(SimulationSnapshot state, PublicState? observed, int energy, int escapes, string? specialRisk)
    {
        var sim = state.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var hero = sim.State.GetCreature(_player.Creature);
        return new(state.Turn, hero.CurrentHp, hero.Block, sim.State.GetPlayerCombatState(_player).Energy,
            observed?.Menu.Enemies.Sum(e => e.Incoming) ?? -1, _enemies.Sum(e => sim.State.GetCreature(e).CurrentHp),
            combat.EffectivePowers().SingleOrDefault(p => p.Id.Entry == "SANDPIT_POWER")?.Amount,
            state.PlayerDead, state.AllEnemiesDead, energy, escapes, specialRisk);
    }

    private static Candidate? Select(IEnumerable<Candidate> rows)
        => rows.Where(r => r.Stop is "victory" or "one_player_round")
            .OrderByDescending(r => r.Endpoint.AllEnemiesDead)
            .ThenByDescending(r => r.Endpoint.Sandpit >= 2)
            .ThenByDescending(r => r.Endpoint.Hp)
            .ThenBy(r => r.Endpoint.EnemyHp)
            .ThenBy(r => r.Endpoint.EscapeEnergy).FirstOrDefault();

    internal void RunTargetedSearch()
    {
        if (Environment.GetEnvironmentVariable("M1Q5_SEARCH") != "1")
        {
            File.WriteAllText(Path.Combine(_output, "public.json"), JsonSerializer.Serialize(new
                { observations = _publicChecks, successors = _successorChecks }, Json));
            return;
        }
        if (_matched != PrefixLength || !Ready)
            throw new InvalidOperationException("Search requires strict native parent parity");
        var initial = ObservePrediction(_state);
        var native = ReadNative(FastCombat.Observe(_combat));
        bool publicParentEqual = JsonNode.DeepEquals(JsonSerializer.SerializeToNode(initial, Json),
            JsonSerializer.SerializeToNode(native, Json));
        var candidates = publicParentEqual ? Goals.Select(goal => Rollout(goal, true)).ToArray() : [];
        var parentStamp = _digest;
        var samples = new List<object>();
        if (publicParentEqual)
        {
            foreach (int budget in new[] { 1, 2, 4, 8 })
            {
                for (int repeat = 0; repeat < 7; repeat++)
                {
                    long alloc = GC.GetAllocatedBytesForCurrentThread();
                    long started = Stopwatch.GetTimestamp();
                    var goals = (budget == 1 ? Goals.Skip(1).Take(1) : Goals.Take(budget)).ToArray();
                    double generationMs = Elapsed(started);
                    var rows = goals.Select(goal => Rollout(goal, false)).ToArray();
                    long selection = Stopwatch.GetTimestamp();
                    var selected = Select(rows)?.Name;
                    double selectionMs = Elapsed(selection);
                    samples.Add(new { budget, ms = Elapsed(started), bytes = GC.GetAllocatedBytesForCurrentThread() - alloc,
                        generationMs, selectionMs, selected, transitions = rows.Sum(row => row.Transitions),
                        observeMs = rows.Sum(row => row.ObserveMs), policyMs = rows.Sum(row => row.PolicyMs),
                        advanceMs = rows.Sum(row => row.AdvanceMs), evaluateMs = rows.Sum(row => row.EvaluateMs) });
                }
            }
        }
        File.WriteAllText(Path.Combine(_output, "search.json"), JsonSerializer.Serialize(new
        {
            publicParentEqual, initial, native, parentUnchanged = parentStamp == Digest(Shadow(_state)),
            parentHash = parentStamp,
            visitedDistinctSuccessors = _statesSeen.Count, candidates,
            selection = new[] { 2, 4, 8 }.Select(budget => new
            {
                budget, selected = Select(candidates.Take(budget))?.Name,
                distinctSuccessors = candidates.Take(budget).SelectMany(c => c.Decisions)
                    .Select(d => d.SuccessorHash).Distinct().Count(),
            }),
            samples, peakWorkingSetBytes = Process.GetCurrentProcess().PeakWorkingSet64,
        }, Json));
    }
}
