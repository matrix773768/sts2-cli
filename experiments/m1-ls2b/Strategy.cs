using System.Diagnostics;
using System.Text.Json;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    // Only public scalar projections and the current legal menu reach the ranking function.
    private sealed record Weights(int Damage, int Block, int Power, int Draw, int Unscored)
    {
        public static Weights Read(JsonElement value)
        {
            Fields(value, "damage", "block", "power", "draw", "unscored");
            return new(Number(value, "damage", 1, 12), Number(value, "block", 1, 12),
                Number(value, "power", 0, 60), Number(value, "draw", 0, 40),
                Number(value, "unscored", 0, 24));
        }
    }

    private static void Fields(JsonElement obj, params string[] keys)
    {
        var names = obj.EnumerateObject().Select(p => p.Name).ToArray();
        if (names.Length != keys.Length || !names.ToHashSet().SetEquals(keys))
            throw new ArgumentException("StrategySpec fields differ from v1");
    }

    private static int Number(JsonElement obj, string key, int min, int max)
    {
        int n = obj.GetProperty(key).GetInt32();
        return min <= n && n <= max ? n : throw new ArgumentException(key);
    }

    private sealed record Spec(Weights Opening, Weights Finish, int SetupTurns, int FinishPct,
        int ReservePct, string Target)
    {
        public static Spec Read(JsonElement obj)
        {
            Fields(obj, "version", "objective", "potion_policy", "opening", "finish", "setup_turns",
                "finish_pct", "reserve_pct", "target");
            var target = obj.GetProperty("target").GetString();
            if (obj.GetProperty("version").GetString() != "ls2b.spec.v1" ||
                obj.GetProperty("objective").GetString() != "surviving_victory" ||
                obj.GetProperty("potion_policy").GetString() != "preserve" ||
                target is not ("weakest" or "threat" or "largest"))
                throw new ArgumentException("Unknown StrategySpec vocabulary");
            return new(Weights.Read(obj.GetProperty("opening")), Weights.Read(obj.GetProperty("finish")),
                Number(obj, "setup_turns", 0, 5), Number(obj, "finish_pct", 10, 90),
                Number(obj, "reserve_pct", 0, 80), target);
        }
    }

    private static (Option, string) SelectSpec(Spec spec, Option[] menu, PublicState view,
        int elapsedTurns, int enemyHp, int initialEnemyHp, int maxHp)
    {
        int threat = Math.Max(0, view.Menu.Enemies.Sum(e => e.Incoming) - view.Menu.Block);
        bool survival = threat > 0 && 100 * (view.Hp - threat) <= spec.ReservePct * maxHp;
        bool finish = elapsedTurns >= spec.SetupTurns || 100 * enemyHp <= spec.FinishPct * initialEnemyHp;
        var weights = finish ? spec.Finish : spec.Opening;
        var enemies = view.Menu.Enemies;
        var focus = spec.Target switch
        {
            "threat" => enemies.OrderByDescending(e => e.Incoming).ThenBy(e => e.Hp + e.Block).FirstOrDefault(),
            "largest" => enemies.OrderByDescending(e => e.Hp + e.Block).FirstOrDefault(),
            _ => enemies.OrderBy(e => e.Hp + e.Block).FirstOrDefault()
        };
        Option best = menu.Single(o => o.Action.Kind == PlanActionKind.EndTurn);
        int bestScore = 0;
        foreach (var option in menu)
        {
            if (option.Card is not { } c) continue;
            var target = c.Target == null ? null : enemies.First(e => e.Id == c.Target);
            int damage = target == null ? c.Damage : Math.Clamp(c.Damage - target.Block, 0, target.Hp);
            int saved = Math.Clamp(c.Block, 0, threat);
            bool lethal = target != null && damage >= target.Hp;
            int score = weights.Damage * damage + weights.Block * saved +
                weights.Draw * c.Draw + (c.Power ? weights.Power : 0) - 2 * c.Energy;
            if (damage == 0 && c.Block == 0 && c.Draw == 0 && !c.Power) score += weights.Unscored;
            if (target != null && damage > 0 && target.Id == focus?.Id) score += 11;
            if (lethal) score += 30 + target!.Incoming * weights.Block;
            if (survival) score += 18 * (saved + (lethal ? Math.Min(threat, target!.Incoming) : 0));
            if (score > bestScore) { bestScore = score; best = option; }
        }
        return (best, survival ? "survival" : finish ? "finish" : "opening");
    }

    internal object RunSpec(JsonElement json)
    {
        var spec = Spec.Read(json);
        if (_potions) throw new ArgumentException("v1 requires dry execution");
        var trace = new List<object>();
        var node = _root;
        string? detail = null;
        _watch.Start();
        try
        {
            while (node.Frame.Stop == "active" && node.Depth < ActionLimit && Continue())
            {
                var menu = Menu(node);
                var (action, phase) = SelectSpec(spec, menu, node.View!, node.Frame.Turn - _root.Frame.Turn,
                    node.Frame.Remaining, _root.Frame.Remaining, node.Frame.MaxHp);
                trace.Add(new { phase, node.Frame.Turn, node.Frame.Hp, node.Frame.Energy,
                    incoming = Incoming(node), node.Frame.Block, legal_count = menu.Length, action = action.Action });
                var next = Advance(node, action);
                if (next == null) break;
                node = next;
            }
        }
        catch (NotSupportedException e) { detail = e.Message; }
        _watch.Stop();
        if (_root.Frame.Stamp != Digest(_root.State!)) throw new InvalidOperationException("Source mutated");
        var end = node.Frame;
        var path = Path(node).Skip(1).ToArray();
        return new
        {
            status = detail != null ? "unsupported" : end.Stop != "active" ? end.Stop : _limit ?? "action_cap",
            detail = detail ?? (end.Stop == "unsupported" ? end.Boundary : null), end.Gaps, trace,
            transitions = _used, cap = _cap, root_unchanged = true, root_stamp = _root.Frame.Stamp,
            hot_ms = _watch.Elapsed.TotalMilliseconds, replay_ms = _replayMs,
            remaining = end.Remaining, initial_enemy_hp = _root.Frame.Remaining,
            resource = new { end.Hp, end.MaxHp, end.Gold, end.Potions, hp_lost = end.CumulativeLoss },
            actions = path.Select(n => n.Option!.Action).ToArray(), stamps = path.Select(n => n.Frame.Stamp).ToArray(),
            route_key = RouteKey(node)
        };
    }
}
