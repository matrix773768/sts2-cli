using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private sealed record QualityWin(string Key, int At, int Hp, int HpLost, string?[] Potions,
        string Origin, int AnchorDepth, PlanAction[] Actions, string[] Stamps);

    internal object RunQuality(JsonElement request)
    {
        var json = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
        json.Converters.Add(new JsonStringEnumConverter());
        var seed = request.GetProperty("seed_actions").Deserialize<PlanAction[]>(json)!;
        var stamps = request.GetProperty("seed_stamps").Deserialize<string[]>(json)!;
        if (_potions || seed.Length is < 1 or > ActionLimit || stamps.Length != seed.Length)
            throw new ArgumentException("Expected a bounded dry incumbent and its exact stamps");

        var attempts = new List<object>();
        var wins = new List<QualityWin>();
        int seedTransitions = 0;
        string rootBefore = _root.Frame.Stamp;
        _watch.Start();
        try
        {
            var current = _root;
            foreach (var (action, stamp) in seed.Zip(stamps))
            {
                var serialized = JsonSerializer.Serialize(action);
                var option = Menu(current).Single(o => JsonSerializer.Serialize(o.Action) == serialized);
                var next = Advance(current, option);
                seedTransitions = _used;
                if (next is null) break;
                if (next.Frame.Stamp != stamp)
                    throw new InvalidOperationException("Charged incumbent reconstruction differs");
                current = next;
            }
            if (seedTransitions == seed.Length && current.Frame.Stop == "predicted_win")
                Improve(Path(current), attempts, wins);
            else
                _detail = "incumbent_not_reconstructed";
        }
        catch (NotSupportedException error)
        {
            _limit ??= "unsupported";
            _detail = error.Message;
            seedTransitions = Math.Min(_used, seed.Length);
        }
        _watch.Stop();
        if (Digest(_root.State!) != rootBefore)
            throw new InvalidOperationException("Quality search mutated root");
        _process.Refresh();
        return new
        {
            status = _limit ?? "alternatives_exhausted", detail = _detail, transitions = _used,
            seed_transitions = seedTransitions, cap = _cap, root_stamp = rootBefore, root_unchanged = true,
            hot_ms = _watch.Elapsed.TotalMilliseconds, peak_working_set_bytes = _process.PeakWorkingSet64,
            reused_prefix_transitions = _reused, candidates = wins, attempts,
            transition_faults = _transitionFaults,
        };
    }

    private void Improve(List<Node> path, List<object> attempts, List<QualityWin> wins)
    {
        var incumbent = path[^1];
        var known = new HashSet<string> { RouteKey(incumbent) };
        // Prefer prefixes before a turn that lost HP. Deeper prefixes make cheaper controls.
        var losses = path.Skip(1).GroupBy(n => n.Option!.Action.Turn).ToDictionary(
            group => group.Key, group => group.Last().Frame.CumulativeLoss -
                                         group.First().Parent!.Frame.CumulativeLoss);
        var anchors = path.SkipLast(1).OrderByDescending(n => losses[n.Frame.Turn])
            .ThenByDescending(n => n.Depth).Take(20).ToArray();
        Keep(anchors.Append(_root));
        foreach (string strategy in new[] { "DEFENSIVE", "AGGRO", "ENGINE", "Q1" })
        {
            foreach (var anchor in anchors)
            {
                if (!Continue()) return;
                var origin = path[anchor.Depth + 1].Option!;
                var preferred = Pick(anchor, strategy);
                // Alternate first decisions as well as the policy used to finish the route.
                var replacement = ReferenceEquals(preferred, origin) && strategy != "Q1"
                    ? Menu(anchor).Where(o => !ReferenceEquals(o, origin))
                        .OrderByDescending(o => strategy == "DEFENSIVE"
                            ? o.Card?.Block ?? 0 : o.Card?.Damage ?? 0).FirstOrDefault()
                    : preferred;
                if (replacement == null || ReferenceEquals(replacement, origin) && strategy == "Q1")
                    continue;

                var rule = new Intervention(anchor.Frame.Stamp, "single_action", replacement, strategy, null, 0);
                int start = _used;
                var roll = Rollout(new(new(strategy, [rule], null, "winning_prefix"), anchor));
                _reused += anchor.Depth;
                string? key = null;
                if (roll.Stop == "predicted_win")
                {
                    key = RouteKey(roll.End);
                    var end = roll.End.Frame;
                    if (known.Add(key))
                    {
                        var suffix = Path(roll.End).Skip(1).ToArray();
                        wins.Add(new(key, _used, end.Hp, end.CumulativeLoss, end.Potions, strategy,
                            anchor.Depth, suffix.Select(n => n.Option!.Action).ToArray(),
                            suffix.Select(n => n.Frame.Stamp).ToArray()));
                    }
                }
                attempts.Add(new { anchor = anchor.Depth, strategy, alternative = replacement.Action,
                    stop = roll.Stop, roll.Detail, transitions = _used - start, win_key = key });
                Keep(anchors.Append(_root));
            }
        }
    }
}
