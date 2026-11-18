using System.Diagnostics;
using System.Text.Json;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private static readonly string[] Strategies = ["Q1", "AGGRO", "DEFENSIVE", "ENGINE"];
    private static readonly HashSet<string> Growth = ["RAMPAGE", "INFERNO"];
    private static readonly HashSet<string> Flow = ["OFFERING", "ENLIGHTENMENT", "HEADBUTT"];
    private const int QueueLimit = 32;
    private const int BeamWidth = 8;

    private sealed record Intervention(string Anchor, string Mode, Option? Forced, string Strategy,
        uint? Focus, int Window);
    private sealed record RoutePlan(string Strategy, Intervention[] Interventions,
        int? ParentRouteId, string RepairReason);
    private sealed record Scheduled(RoutePlan Plan, Node Anchor);
    private sealed record FailureReport(int RouteId, string[] FailureType, int TerminalRound, string TerminalCause,
        uint? CriticalEnemy, int DamageGap, int SurvivalGap, int[] SuspectedDecisions, object SupportingEvidence);
    private sealed record RolloutResult(Node End, string Stop, string? Detail);

    private readonly List<object> _routes = [];

    private static int Incoming(Node node) => node.View!.Menu.Enemies.Sum(e => e.Incoming);
    private static int Threat(Node node) => Math.Max(0, Incoming(node) - node.Frame.Block);
    private static bool EngineCard(Option option) => option.Card is { } c &&
        (c.Power || Growth.Contains(c.Id) || Flow.Contains(c.Id));

    private Option Pick(Node node, string strategy, uint? focus = null)
    {
        var menu = Menu(node);
        var cards = menu.Where(o => o.Card != null).ToArray();
        var end = menu[^1];
        var view = node.View!;
        if (strategy == "Q1")
        {
            var choice = RealCombat.Decide(view.Menu, true);
            return choice == null ? end : cards.First(o => ReferenceEquals(o.Card, choice));
        }
        if (cards.Length == 0) return end;

        int incoming = Threat(node);
        bool urgent = incoming >= Math.Max(1, node.Frame.Hp - 3);
        var defense = cards.Where(o => o.Card!.Block > 0)
            .OrderByDescending(o => Math.Min(incoming, o.Card!.Block)).ThenBy(o => o.Card!.Energy).FirstOrDefault();
        int Effective(Option o)
        {
            var c = o.Card!;
            if (c.Target is not { } target) return c.Damage;
            var enemy = view.Menu.Enemies.First(e => e.Id == target);
            return Math.Clamp(c.Damage - enemy.Block, 0, enemy.Hp);
        }
        var kill = cards.Where(o => o.Card!.Target is { } id &&
                Effective(o) >= view.Menu.Enemies.First(e => e.Id == id).Hp)
            .OrderByDescending(o => view.Menu.Enemies.First(e => e.Id == o.Card!.Target).Incoming).FirstOrDefault();
        var attacks = cards.Where(o => Effective(o) > 0).ToArray();
        var chosenFocus = focus ?? view.Menu.Enemies.OrderBy(e => e.Hp + e.Block - e.Incoming)
            .FirstOrDefault()?.Id;
        var attack = attacks.OrderByDescending(o => o.Card!.Target == chosenFocus)
            .ThenByDescending(Effective).ThenBy(o => o.Card!.Energy).FirstOrDefault();
        var draw = cards.Where(o => o.Card!.Draw > 0).OrderByDescending(o => o.Card!.Draw)
            .ThenBy(o => o.Card!.Energy).FirstOrDefault();
        var forge = menu.FirstOrDefault(o => o.Action.PotionId == "BLESSING_OF_THE_FORGE");
        var dex = menu.FirstOrDefault(o => o.Action.PotionId == "DEXTERITY_POTION");
        var flex = menu.FirstOrDefault(o => o.Action.PotionId == "FLEX_POTION");

        // A kill that removes the threatening attacker can be stronger than a block.
        if (kill != null && (strategy != "ENGINE" || urgent))
            return kill;
        if (incoming >= 6 && dex != null && defense != null && (urgent || strategy == "DEFENSIVE"))
            return dex;
        if (urgent && defense != null)
            return defense;

        if (strategy == "DEFENSIVE")
        {
            if (incoming > 0 && defense != null) return defense;
            if (forge != null && cards.Count(o => o.Card!.Block > 0 || o.Card.Damage > 0) >= 3) return forge;
            if (flex != null && attacks.Length >= 2 && view.Energy >= 2) return flex;
            return attack ?? draw ?? cards.FirstOrDefault(EngineCard) ?? end;
        }
        if (strategy == "ENGINE")
        {
            var offering = cards.FirstOrDefault(o => o.Card!.Id == "OFFERING" && node.Frame.Hp > 8);
            var engine = cards.FirstOrDefault(o => o.Card!.Power || Growth.Contains(o.Card.Id) ||
                o.Card.Id == "ENLIGHTENMENT" && cards.Count(c => c.Card!.Energy >= 2) >= 2 ||
                o.Action.Choice?.Cards.Any(t => Growth.Contains(t.CardId)) == true);
            if (forge != null && (engine != null || draw != null) && cards.Length >= 3) return forge;
            if (offering != null) return offering;
            if (engine != null) return engine;
            if (draw != null && view.Energy > draw.Card!.Energy) return draw;
            if (incoming > 0 && defense != null) return defense;
            if (flex != null && attack != null && attacks.Length >= 2) return flex;
            return attack ?? draw ?? end;
        }

        if (forge != null && attacks.Length >= 2 && cards.Length >= 3) return forge;
        if (flex != null && attacks.Length >= 2 && view.Energy >= 2) return flex;
        if (attack != null) return attack;
        if (draw != null && view.Energy > draw.Card!.Energy) return draw;
        return incoming > 0 && defense != null ? defense : end;
    }

    private RolloutResult Rollout(Scheduled task)
    {
        Node current = task.Anchor;
        var rule = task.Plan.Interventions.SingleOrDefault();
        if (rule != null && rule.Anchor != current.Frame.Stamp)
            throw new InvalidOperationException("Repair anchor differs from its recorded state");
        string strategy = rule?.Mode == "strategy_rebuild" ? rule.Strategy : task.Plan.Strategy;
        try
        {
            while (current.Frame.Stop == "active" && current.Depth < ActionLimit && Continue())
            {
                int offset = current.Depth - task.Anchor.Depth;
                bool window = rule?.Mode == "critical_window" && offset < rule.Window &&
                    current.Frame.Turn == task.Anchor.Frame.Turn;
                Option selected;
                if (offset == 0 && rule?.Forced is { } forced)
                    selected = Menu(current).First(o => ReferenceEquals(o, forced));
                else
                    selected = Pick(current, window ? rule!.Strategy : strategy, window ? rule!.Focus : null);
                var next = Advance(current, selected);
                if (next == null) break;
                current = next;
            }
        }
        catch (NotSupportedException error)
        {
            return new(current, "unsupported", error.Message);
        }
        string stop = current.Frame.Stop != "active" ? current.Frame.Stop : "truncated";
        return new(current, stop, stop == "truncated" ? _limit ?? "action_cap" : null);
    }

    private FailureReport Diagnose(int id, List<Node> path, Node early, Node late)
    {
        var terminal = path[^1];
        var parent = path[^2];
        _ = Menu(parent);
        var threat = parent.View!.Menu.Enemies.OrderByDescending(e => e.Incoming).FirstOrDefault();
        int gap = Math.Max(0, Threat(parent) - parent.Frame.Hp + 1);
        var causes = new List<string>();
        if (terminal.Frame.Remaining > 0) causes.Add("damage_progress");
        if (gap > 0) causes.Add("survival");
        if (threat is { Incoming: > 0 } && terminal.Frame.Enemies.Any(e => e.Id == threat.Id && e.Hp > 0))
            causes.Add("threat_alive_at_death");
        if (early.Options!.Any(EngineCard) && !path.Skip(1).Take(4).Any(n => EngineCard(n.Option!)))
            causes.Add("engine_not_started_in_first_four_actions");
        if (parent.Frame.Energy > 0 && parent.Options!.Any(o => o.Card != null))
            causes.Add("unused_legal_energy");
        if (_potions && late.Options!.Any(o => o.Action.Kind == PlanActionKind.UsePotion))
            causes.Add("potion_still_available_in_critical_window");
        bool special = parent.View.Sandpit == 1;
        if (special) causes.Add("special_deadline_visible");
        if (causes.Count == 0) causes.Add("unexplained");
        return new(id, causes.ToArray(), terminal.Frame.Turn,
            special ? "possible_sandpit" : gap > 0 ? "revealed_attack_can_be_lethal" : "native_cause_unconfirmed",
            threat?.Id, terminal.Frame.Remaining, gap, [early.Id, late.Id],
            new { parent.Frame.Hp, incoming = Incoming(parent), parent.Frame.Block, parent.Frame.Energy,
                enemy = threat, last_action = terminal.Option?.Action, interpretation = "candidate_hypotheses" });
    }

    private void Routes(string arm)
    {
        var queue = new Queue<Scheduled>();
        var endpoints = new List<Frame>();
        var seen = new HashSet<(int, string, string, int, string, uint?)>();
        void Add(Node anchor, string strategy, int? parentId, string reason, Intervention? rule = null)
        {
            int forced = rule?.Forced == null ? -1 : Array.IndexOf(Menu(anchor), rule.Forced);
            var key = (anchor.Id, strategy, rule?.Mode ?? "initial", forced, rule?.Strategy ?? "", rule?.Focus);
            if (queue.Count < QueueLimit && seen.Add(key))
                queue.Enqueue(new(new(strategy, rule == null ? [] : [rule], parentId, reason), anchor));
        }
        foreach (string strategy in arm == "A" ? ["Q1"] : Strategies)
            Add(_root, strategy, null, "initial_strategy");

        while (queue.Count > 0 && Continue())
        {
            var task = queue.Dequeue();
            int id = _routes.Count;
            int start = _used;
            long clock = Stopwatch.GetTimestamp();
            if (task.Plan.ParentRouteId != null)
            {
                _branches++;
                _reused += task.Anchor.Depth;
            }
            var roll = Rollout(task);
            var path = Path(roll.End);
            var available = path.Where(n => n.State != null && n.Frame.Stop == "active" && n.Depth < roll.End.Depth).ToArray();
            bool won = Win(roll.End);
            FailureReport? failure = null;
            if (arm == "A" && roll.Stop == "death" && available.Length > 0)
            {
                failure = Diagnose(id, path, available[0], available[^1]);
                _diagnoses++;
            }
            if (arm != "A" && roll.Stop == "death" && available.Length > 0)
            {
                string changeTo = Strategies[(Array.IndexOf(Strategies, task.Plan.Strategy) + 1) % Strategies.Length];
                var early = available[Math.Min(1, available.Length - 1)];
                var late = available[available.Length / 2];
                string targeted = "DEFENSIVE";
                uint? focus = null;
                if (arm == "C")
                {
                    early = available.Take(8).FirstOrDefault(n => Menu(n).Any(EngineCard)) ?? early;
                    late = available.FirstOrDefault(n => n.Frame.Turn == path[^2].Frame.Turn) ?? late;
                    _ = Menu(late);
                    failure = Diagnose(id, path, early, late);
                    _diagnoses++;
                    focus = failure.CriticalEnemy;
                    targeted = failure.SurvivalGap > 0 ? "DEFENSIVE" :
                        failure.FailureType.Contains("engine_not_started_in_first_four_actions") ? "ENGINE" : "AGGRO";
                    changeTo = targeted == task.Plan.Strategy ? changeTo : targeted;
                }
                Option? Original(Node n) => path[n.Depth + 1].Option;
                var alternate = Menu(late).Where(o => !ReferenceEquals(o, Original(late))).ToArray();
                if (alternate.Length > 0)
                {
                    var preferred = arm == "C" ? Pick(late, targeted, focus) : alternate[0];
                    if (ReferenceEquals(preferred, Original(late)))
                        preferred = arm == "C" ? alternate.OrderByDescending(o => targeted == "DEFENSIVE"
                            ? o.Card?.Block ?? (o.Action.Kind == PlanActionKind.UsePotion ? 5 : 0)
                            : o.Card?.Damage ?? 0).First() : alternate[0];
                    Add(late, task.Plan.Strategy, id, "late_alternative",
                        new(late.Frame.Stamp, "single_action", preferred, task.Plan.Strategy, null, 0));
                }
                Add(late, task.Plan.Strategy, id, "turn_window",
                    new(late.Frame.Stamp, "critical_window", null, targeted, focus, 3));
                Add(early, task.Plan.Strategy, id, "early_strategy_switch",
                    new(early.Frame.Stamp, "strategy_rebuild", null, changeTo, null, 0));
                var undirected = Menu(early).Reverse().FirstOrDefault(o => !ReferenceEquals(o, Original(early)));
                if (undirected != null)
                    Add(early, task.Plan.Strategy, id, "undirected",
                        new(early.Frame.Stamp, "single_action", undirected, task.Plan.Strategy, null, 0));
            }
            Frame? comparison = task.Plan.ParentRouteId is { } originalId ? endpoints[originalId] : null;
            endpoints.Add(roll.End.Frame);
            _routes.Add(new
            {
                id, task.Plan, anchor = task.Anchor.Id, stop = won ? "predicted_win" :
                    roll.Stop == "predicted_win" ? "rejected_native_candidate" : roll.Stop,
                roll.Detail, transitions = _used - start, first_transition = start + 1, last_transition = _used,
                prefix_reused = task.Anchor.Depth, nodes = path.Select(n => n.Id).ToArray(), failure,
                counterfactual = comparison == null ? null : new
                {
                    parent_stop = comparison.Stop, terminal_turn_delta = roll.End.Frame.Turn - comparison.Turn,
                    remaining_enemy_hp_delta = roll.End.Frame.Remaining - comparison.Remaining,
                },
                rollout_ms = Stopwatch.GetElapsedTime(clock).TotalMilliseconds,
                turns = path.Skip(1).GroupBy(n => n.Option!.Action.Turn).Select(g =>
                {
                    var first = g.First(); var last = g.Last();
                    return new { turn = g.Key, hp = last.Frame.Hp,
                        player_loss = last.Frame.CumulativeLoss - (first.Parent?.Frame.CumulativeLoss ?? first.Frame.CumulativeLoss),
                        enemy_progress = (first.Parent?.Frame.Remaining ?? first.Frame.Remaining) - last.Frame.Remaining,
                        kills = (first.Parent?.Frame.Alive ?? first.Frame.Alive) - last.Frame.Alive };
                }).ToArray(),
                mechanisms = path.Skip(1).Where(n => EngineCard(n.Option!) ||
                    n.Option!.Action.Kind == PlanActionKind.UsePotion).Select(n => n.Id).ToArray(),
            });
            if (won) return;
            if (arm == "A")
            {
                _limit ??= roll.Stop == "predicted_win" ? "rejected_native_candidate" : roll.Stop;
                _detail ??= roll.Detail;
            }
            Keep(queue.Select(q => q.Anchor).Append(_root));
        }
    }

    private void Beam()
    {
        List<Node> layer = [_root];
        for (int depth = 0; depth < ActionLimit && layer.Count > 0 && Continue(); depth++)
        {
            var next = new List<(double Rank, Node Node)>();
            var reached = new HashSet<string>();
            foreach (var parent in layer)
            {
                if (!Continue()) break;
                Option[] options;
                try { options = Menu(parent); }
                catch (NotSupportedException) { continue; }
                foreach (var option in options)
                {
                    Node? child;
                    try { child = Advance(parent, option); }
                    catch (NotSupportedException) { continue; }
                    if (child == null) break;
                    _branches++;
                    _reused += parent.Depth;
                    if (Win(child)) return;
                    var frame = child.Frame;
                    if (frame.Stop != "active" || !reached.Add(frame.Stamp))
                    {
                        Release(child);
                        continue;
                    }
                    double rank = 2.5 * frame.Hp - frame.Remaining - 8 * frame.Alive +
                        .65 * frame.Block + 1.25 * frame.Energy;
                    next.Add((rank, child));
                    if (next.Count > BeamWidth)
                    {
                        int last = next.IndexOf(next.OrderBy(t => t.Rank).ThenByDescending(t => t.Node.Id).First());
                        Release(next[last].Node);
                        next.RemoveAt(last);
                    }
                }
            }
            layer = next.OrderByDescending(t => t.Rank).ThenBy(t => t.Node.Id).Select(t => t.Node).ToList();
            Keep(layer.Append(_root));
        }
    }

    // Isolated fixture entry point. The benchmark never supplies a forced action.
    private void ProbeRepair(JsonElement fixture)
    {
        int prefixLength = fixture.GetProperty("prefix_length").GetInt32();
        if (prefixLength is < 1 or >= ActionLimit) throw new ArgumentOutOfRangeException(nameof(fixture));
        var anchor = _root;
        for (int i = 0; i < prefixLength; i++)
            anchor = Advance(anchor, Pick(anchor, "Q1")) ?? throw new InvalidOperationException("Fixture prefix truncated");
        var original = new RoutePlan("Q1", [], null, "fixture_control");
        var baseline = Rollout(new(original, anchor));
        var substitute = Menu(anchor).Single(o => o.Card?.HandIndex == fixture.GetProperty("hand_index").GetInt32()
            && o.Action.TargetCombatId == fixture.GetProperty("target").GetUInt32());
        var rule = new Intervention(anchor.Frame.Stamp, "single_action", substitute, "Q1", null, 0);
        var repair = new RoutePlan("Q1", [rule], 0, "fixture_alternative");
        _reused += anchor.Depth;
        _branches++;
        var candidate = Rollout(new(repair, anchor));
        if (Digest(anchor.State!) != anchor.Frame.Stamp || baseline.Stop != "death" || !Win(candidate.End))
            throw new InvalidOperationException($"Fixture did not demonstrate the intended delta: {baseline.Stop}/{candidate.Stop}");
        _routes.Add(new { id = 0, plan = original, anchor = anchor.Id, stop = baseline.Stop,
            nodes = Path(baseline.End).Select(n => n.Id).ToArray() });
        _routes.Add(new { id = 1, plan = repair, anchor = anchor.Id, stop = candidate.Stop,
            nodes = Path(candidate.End).Select(n => n.Id).ToArray(), parent_unchanged = true });
    }
}
