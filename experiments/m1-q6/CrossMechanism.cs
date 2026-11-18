using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed partial class RouteProbe
{
    private const int CandidateLimit = 4;
    private const int RouteLimit = 18;
    private const double WallLimitMs = 250;
    private static readonly int[] Caps = [16, 32, 64];
    private static bool Regent => Environment.GetEnvironmentVariable("M1Q6_CASE") == "regent";

    private sealed record ArmRoute(int Slot, string First, List<Decision> Decisions, Endpoint Endpoint,
        string Stop, int Transitions, double ObserveMs, double PolicyMs, double AdvanceMs, double EvaluateMs,
        string[] Powers, string[] EnemyPowers, string? Detail);
    private sealed record ArmRun(string Arm, int Cap, int Transitions, int? DistinctSuccessors,
        int SharedParentStepsAvoided, int? Selected, double GenerateMs, double SelectMs, double TotalMs,
        long Bytes, ArmRoute[] Routes);

    private static string MoveId(FastCombat.Move? move) => move?.Id ?? "END_TURN";

    private static FastCombat.Move?[] FirstMoves(string arm, PublicState state)
    {
        if (arm == "A")
            return [FastCombat.Decide(state.Menu, true)];
        var legal = state.Menu.Moves.Cast<FastCombat.Move?>().Append(null)
            .OrderBy(MoveId, StringComparer.Ordinal).ThenBy(m => m?.HandIndex).ThenBy(m => m?.Target).ToArray();
        if (arm == "B")
            return legal.Take(CandidateLimit).ToArray();

        var cards = state.Menu.Moves;
        int uncovered = Math.Max(0, state.Menu.Enemies.Sum(e => e.Incoming) - state.Menu.Block);
        var defense = cards.Where(m => m.Block > 0 && (!Regent || m.Id != "THE_GAMBIT"))
            .OrderByDescending(m => m.Block).FirstOrDefault();
        var attack = cards.Where(m => m.Damage > 0).OrderByDescending(m => m.Damage).FirstOrDefault();
        var draw = cards.Where(m => m.Draw > 0).OrderByDescending(m => m.Draw).FirstOrDefault();
        var gambit = cards.FirstOrDefault(m => m.Id == "THE_GAMBIT" && m.Block >= uncovered);
        var escape = state.Sandpit == 1 ? cards.FirstOrDefault(m => m.Id == "FRANTIC_ESCAPE") : null;
        FastCombat.Move?[] preferred = Regent ? [defense, attack, gambit] : [escape, attack, uncovered > 0 ? defense : null, draw];
        return preferred.Where(m => m != null).Concat(legal.Where(m => !Regent || m?.Id != "THE_GAMBIT" || gambit != null))
            .Distinct().Take(CandidateLimit).ToArray();
    }

    private ArmRoute Extend(string arm, int slot, FastCombat.Move? first, PublicState initial,
        bool audit, int remaining, long runStart)
    {
        var state = _state;
        var decisions = new List<Decision>();
        int transitions = 0, escapes = 0, energy = 0;
        double advance = 0, observe = 0, policy = 0, evaluate = 0;
        string stop = "action_cap";
        string? detail = null;
        string? special = null;
        PublicState? final = initial;
        try
        {
            while (transitions < RouteLimit)
            {
                if (transitions >= remaining || Elapsed(runStart) >= WallLimitMs)
                {
                    stop = transitions >= remaining ? "transition_cap" : "wall_cap";
                    break;
                }
                long start = Stopwatch.GetTimestamp();
                var observation = transitions == 0 ? initial : ObservePrediction(state);
                observe += Elapsed(start);
                start = Stopwatch.GetTimestamp();
                var move = transitions == 0 ? first :
                    (arm != "A" && observation.Sandpit == 1
                        ? observation.Menu.Moves.FirstOrDefault(m => m.Id == "FRANTIC_ESCAPE")
                        : null) ?? FastCombat.Decide(observation.Menu, true);
                var action = ToPlan(state, move);
                policy += Elapsed(start);
                if (Elapsed(runStart) >= WallLimitMs)
                {
                    stop = "wall_cap";
                    break;
                }
                start = Stopwatch.GetTimestamp();
                var next = Step(_solver, state, action);
                advance += Elapsed(start);
                transitions++;
                if (!ReferenceEquals(state, _state)) state.ReleaseSimulator();
                state = next;
                final = null;
                decisions.Add(new(new(action.Turn, move == null ? null : new(move.HandIndex, move.Id, move.Target), null),
                    observation, audit ? Digest(Shadow(state)) : null));
                if (move?.Id == "FRANTIC_ESCAPE")
                {
                    escapes++;
                    energy += move.Energy;
                }
                if (state.HasRisk || state.BoundaryReason != SearchBoundaryReason.None)
                {
                    stop = "prediction_boundary";
                    detail = state.BoundaryReason + "/" + state.HasRisk;
                    break;
                }
                if (state.TerminalStamp != null)
                {
                    stop = state.PlayerDead ? "death" : "victory";
                    if (state.PlayerDead && move == null && observation.Sandpit == 1)
                        special = "sandpit_at_one_before_end_turn";
                    break;
                }
                if (state.Turn >= _state.Turn + 2)
                {
                    stop = "common_horizon";
                    break;
                }
            }
            long evaluateStart = Stopwatch.GetTimestamp();
            if (stop is "common_horizon" or "action_cap" or "transition_cap")
                final ??= ObservePrediction(state);
            evaluate = Elapsed(evaluateStart);
        }
        catch (NotSupportedException error)
        {
            stop = "unsupported_public_projection";
            detail = error.Message;
        }

        try
        {
            long start = Stopwatch.GetTimestamp();
            var endpoint = ReadEndpoint(state, final, energy, escapes, special);
            var sim = (SimulatedCombatState)state.Simulator.State.CombatState;
            var powers = sim.EffectivePowers().ToArray();
            var playerPowers = powers.Where(p => ReferenceEquals(p.Owner, _player.Creature))
                .Select(p => $"{p.Id.Entry}:{p.Amount}").Order().ToArray();
            var enemyPowers = powers.Where(p => !ReferenceEquals(p.Owner, _player.Creature))
                .Select(p => $"{p.Owner.CombatId}:{p.Id.Entry}:{p.Amount}").Order().ToArray();
            return new(slot, MoveId(first), decisions, endpoint, stop, transitions, observe, policy, advance,
                evaluate + Elapsed(start), playerPowers, enemyPowers, detail);
        }
        finally
        {
            if (!ReferenceEquals(state, _state)) state.ReleaseSimulator();
        }
    }

    private ArmRun SearchArm(string arm, int cap, bool audit)
    {
        long bytes = GC.GetAllocatedBytesForCurrentThread();
        long start = Stopwatch.GetTimestamp();
        var initial = ObservePrediction(_state);
        var starts = FirstMoves(arm, initial);
        double generate = Elapsed(start);
        int remaining = cap;
        var routes = new List<ArmRoute>();
        foreach (var first in starts)
        {
            if (remaining == 0 || Elapsed(start) >= WallLimitMs)
                break;
            var row = Extend(arm, routes.Count, first, initial, audit, remaining, start);
            routes.Add(row);
            remaining -= row.Transitions;
        }
        long choose = Stopwatch.GetTimestamp();
        var selected = routes.Where(r => r.Stop is "victory" or "common_horizon")
            .OrderByDescending(r => r.Stop == "victory")
            .ThenByDescending(r => r.Endpoint.Hp)
            .ThenByDescending(r => r.Endpoint.Sandpit.GetValueOrDefault())
            .ThenBy(r => r.Endpoint.EnemyHp)
            .ThenBy(r => r.Endpoint.EscapeEnergy).FirstOrDefault();
        double selection = Elapsed(choose);
        double total = Elapsed(start);
        int? distinct = audit
            ? routes.SelectMany(r => r.Decisions).Select(d => d.SuccessorHash).Distinct().Count()
            : null;
        return new(arm, cap, cap - remaining, distinct, Math.Max(0, routes.Count - 1) * PrefixLength,
            selected?.Slot, generate, selection, total, GC.GetAllocatedBytesForCurrentThread() - bytes, routes.ToArray());
    }

    private double RebuildParent()
    {
        long started = Stopwatch.GetTimestamp();
        var state = Step(_solver, null, null);
        try
        {
            foreach (var action in _plan.Take(PrefixLength))
            {
                var next = Step(_solver, state, action);
                state.ReleaseSimulator();
                state = next;
            }
            double elapsed = Elapsed(started);
            if (_digest != Digest(Shadow(state)))
                throw new InvalidOperationException("Rebuilt parent digest changed");
            return elapsed;
        }
        finally { state.ReleaseSimulator(); }
    }

    internal void RunCrossMechanism()
    {
        if (Environment.GetEnvironmentVariable("M1Q5_SEARCH") != "1")
        {
            RunTargetedSearch();
            return;
        }

        string status = "strict_parent_failed";
        PublicState? initial = null;
        PublicState? native = null;
        var audited = new List<ArmRun>();
        var samples = new List<object>();
        var rebuild = new List<double>();
        if (_matched == PrefixLength && Ready)
        {
            status = "unsupported_public_parent";
            try
            {
                initial = ObservePrediction(_state);
                native = ReadNative(FastCombat.Observe(_combat));
                status = JsonNode.DeepEquals(JsonSerializer.SerializeToNode(initial, Json),
                    JsonSerializer.SerializeToNode(native, Json)) ? "pass" : "public_parent_difference";
            }
            catch (NotSupportedException error)
            {
                status += ": " + error.Message;
            }
        }
        if (status == "pass")
        {
            audited.Add(SearchArm("A", Caps[^1], true));
            foreach (int cap in Caps)
            {
                audited.Add(SearchArm("B", cap, true));
                audited.Add(SearchArm("C", cap, true));
            }
            for (int repeat = 0; repeat < 5; repeat++)
            {
                rebuild.Add(RebuildParent());
                foreach (var request in audited)
                {
                    var run = SearchArm(request.Arm, request.Cap, false);
                    samples.Add(new
                    {
                        run.Arm, run.Cap, run.Transitions, run.TotalMs, run.Bytes, run.GenerateMs, run.SelectMs,
                        run.Selected, observeMs = run.Routes.Sum(r => r.ObserveMs),
                        policyMs = run.Routes.Sum(r => r.PolicyMs), advanceMs = run.Routes.Sum(r => r.AdvanceMs),
                        evaluateMs = run.Routes.Sum(r => r.EvaluateMs),
                        stops = run.Routes.Select(r => r.Stop),
                    });
                }
            }
        }
        File.WriteAllText(Path.Combine(_output, "search.json"), JsonSerializer.Serialize(new
        {
            status, matched = _matched, initial, native, parentHash = _digest,
            parentUnchanged = _digest == Digest(Shadow(_state)), audited, samples, rebuildParentMs = rebuild,
            peakWorkingSetBytes = Process.GetCurrentProcess().PeakWorkingSet64,
        }, Json));
    }
}
