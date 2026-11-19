"""Stage an opt-in lean F4 path and isolated phase telemetry."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f6a_b1b", HERE.parent / "m1-b1b/build_probe.py")
b1b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1b)
edit = b1b.b1a.edit


def stage(src):
    b1b.stage(src)
    for name in ("F6Meter.cs", "LeanDigest.cs"):
        (src / name).write_bytes((HERE / name).read_bytes())
    host = src / "Host.cs"
    edit(host, "        var clock = Stopwatch.StartNew();", '''        bool quality = request.GetProperty("cmd").GetString() == "i1_f4";
        bool profile = quality && request.TryGetProperty("f6_profile", out var measurement)
            && measurement.GetBoolean();
        bool lean = quality && request.TryGetProperty("f6_lean", out var optimization)
            && optimization.GetBoolean()
            && (!request.TryGetProperty("include_history", out var history) || !history.GetBoolean());
        var meter = profile ? new F6Meter() : null;
        var clock = Stopwatch.StartNew();''')
    edit(host, "with { MaxDegreeOfParallelism = 1 };",
         "with { MaxDegreeOfParallelism = 1, MeasurePhasePerformance = profile };")
    edit(host, 'GetProperty("rejected").EnumerateArray().Select(x => x.GetString()!).ToHashSet());',
         'GetProperty("rejected").EnumerateArray().Select(x => x.GetString()!).ToHashSet(), lean, meter);')
    edit(host, '''        return new() { ["type"] = "f3b_result", ["root_prepare_ms"] = clock.Elapsed.TotalMilliseconds,
            ["search"] = request.GetProperty("cmd").GetString() == "i1_f4"
                ? search.RunQuality(request)
                : search.Run(arm, request.TryGetProperty("repair_probe", out var probe) ? probe : null) };''',
         '''        var prepareMs = clock.Elapsed.TotalMilliseconds;
        long bytes = GC.GetAllocatedBytesForCurrentThread();
        var gc = Enumerable.Range(0, 3).Select(GC.CollectionCount).ToArray();
        double pause = GC.GetTotalPauseDuration().TotalMilliseconds;
        var result = quality ? search.RunQuality(request)
            : search.Run(arm, request.TryGetProperty("repair_probe", out var probe) ? probe : null);
        var output = new Dictionary<string, object?> { ["type"] = "f3b_result",
            ["root_prepare_ms"] = prepareMs, ["search"] = result };
        if (quality)
        {
            output["f6_runtime"] = new { lean, thread_allocated_bytes = GC.GetAllocatedBytesForCurrentThread() - bytes,
                gc_collections = Enumerable.Range(0, 3).Select(i => GC.CollectionCount(i) - gc[i]).ToArray(),
                gc_pause_ms = GC.GetTotalPauseDuration().TotalMilliseconds - pause };
        }
        if (meter != null)
        {
            var (phases, forks) = F6Meter.Solver(solver);
            output["f6_profile"] = new { adapter = meter.Snapshot(), solver = phases, forks };
        }
        return output;''')
    first = src / "FirstWin.cs"
    edit(first, "    private int _used,", """    private readonly bool _lean;
    private readonly F6Meter? _meter;
    private int _nodeCount;
    private int _used,""")
    edit(first, "bool potions, HashSet<string> rejected)", "bool potions, HashSet<string> rejected, bool lean = false, F6Meter? meter = null)")
    edit(first, "        _cap = cap;", "        _cap = cap;\n        _lean = lean;\n        _meter = meter;")
    edit(first, "        var sim = (CombatPredictionSimulator)snapshot.Simulator;\n        var pc",
         '''        using var timing = _meter?.Measure("record");
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var pc''')
    edit(first, "}).ToArray(), Pile(pc.Hand.Cards), Pile(pc.DrawPile.Cards),",
         "}).ToArray(), _lean ? [] : Pile(pc.Hand.Cards), _lean ? [] : Pile(pc.DrawPile.Cards),")
    edit(first, "Pile(pc.DiscardPile.Cards),\n            Pile(pc.ExhaustPile.Cards), combat.EffectivePowers()",
         "_lean ? [] : Pile(pc.DiscardPile.Cards),\n            _lean ? [] : Pile(pc.ExhaustPile.Cards), _lean ? [] : combat.EffectivePowers()")
    edit(first, "new Node(_history.Count, parent, option, snapshot, frame)", "new Node(_nodeCount++, parent, option, snapshot, frame)")
    edit(first, "        _history.Add(new { id", "        if (!_lean) _history.Add(new { id")
    edit(first, """    private string Digest(SimulationSnapshot snapshot) =>
        Hash(ContinuationStamp.CapturePredicted(_player, (CombatPredictionSimulator)snapshot.Simulator,
            snapshot.Turn, EmptyForecast, snapshot.Turn).StateText);""", """    private string Digest(SimulationSnapshot snapshot)
    {
        using var timing = _meter?.Measure("digest");
        string text = ContinuationStamp.CapturePredicted(_player, (CombatPredictionSimulator)snapshot.Simulator,
            snapshot.Turn, EmptyForecast, snapshot.Turn).StateText;
        return _lean ? HashDigest(text) : Hash(text);
    }""")
    edit(first, "        try { next = _advance(snapshot, option.Action); }", '''        try
        {
            using var timing = _meter?.Measure("replay");
            next = _advance(snapshot, option.Action);
        }''')
    edit(first, "        if (node.Options != null) return node.Options;", '''        if (node.Options != null)
        {
            using var hit = _meter?.Measure("menu_hit");
            return node.Options;
        }
        using var timing = _meter?.Measure("menu_build");''')
    edit(first, "        var set = retained.ToHashSet();",
         '        using var timing = _meter?.Measure("retain");\n        var set = retained as HashSet<Node> ?? retained.ToHashSet();')
    routes = src / "RouteSearch.cs"
    edit(routes, "        Node current = task.Anchor;", '        using var timing = _meter?.Measure("rollout");\n        Node current = task.Anchor;')
    quality = src / "QualitySearch.cs"
    edit(quality, "            foreach (var (action, stamp) in seed.Zip(stamps))", '''            using (var seedTiming = _meter?.Measure("seed"))
            foreach (var (action, stamp) in seed.Zip(stamps))''')
    edit(quality, "                var serialized = JsonSerializer.Serialize(action);\n                var option = Menu(current).Single(o => JsonSerializer.Serialize(o.Action) == serialized);",
         '''                var options = Menu(current);
                Option option;
                using (var timing = _meter?.Measure("seed_action_match"))
                {
                    var serialized = JsonSerializer.Serialize(action);
                    option = options.Single(o => JsonSerializer.Serialize(o.Action) == serialized);
                }''')
    edit(quality, "        var incumbent = path[^1];", '''        using var timing = _meter?.Measure("improve");
        var incumbent = path[^1];''')
    edit(quality, """        var losses = path.Skip(1).GroupBy(n => n.Option!.Action.Turn).ToDictionary(
            group => group.Key, group => group.Last().Frame.CumulativeLoss -
                                         group.First().Parent!.Frame.CumulativeLoss);
        var anchors = path.SkipLast(1).OrderByDescending(n => losses[n.Frame.Turn])
            .ThenByDescending(n => n.Depth).Take(20).ToArray();""",
         """        Node[] anchors;
        using (_meter?.Measure("anchor_layout"))
        {
            var losses = path.Skip(1).GroupBy(n => n.Option!.Action.Turn).ToDictionary(
                group => group.Key, group => group.Last().Frame.CumulativeLoss -
                                             group.First().Parent!.Frame.CumulativeLoss);
            anchors = path.SkipLast(1).OrderByDescending(n => losses[n.Frame.Turn])
                .ThenByDescending(n => n.Depth).Take(20).ToArray();
        }""")
    edit(quality, "        Keep(anchors.Append(_root));\n        foreach", '''        var retained = _lean ? anchors.Append(_root).ToHashSet() : null;
        Keep(retained ?? anchors.Append(_root));
        foreach''')
    edit(quality, """                var origin = path[anchor.Depth + 1].Option!;
                var preferred = Pick(anchor, strategy);
                // Alternate first decisions as well as the policy used to finish the route.
                var replacement = ReferenceEquals(preferred, origin) && strategy != "Q1"
                    ? Menu(anchor).Where(o => !ReferenceEquals(o, origin))
                        .OrderByDescending(o => strategy == "DEFENSIVE"
                            ? o.Card?.Block ?? 0 : o.Card?.Damage ?? 0).FirstOrDefault()
                    : preferred;""", """                using var candidateTiming = _meter?.Measure("candidate_attempt");
                var origin = path[anchor.Depth + 1].Option!;
                Option? replacement;
                using (_meter?.Measure("replacement"))
                {
                    var preferred = Pick(anchor, strategy);
                    // Alternate first decisions as well as the policy used to finish the route.
                    replacement = ReferenceEquals(preferred, origin) && strategy != "Q1"
                        ? Menu(anchor).Where(o => !ReferenceEquals(o, origin))
                            .OrderByDescending(o => strategy == "DEFENSIVE"
                                ? o.Card?.Block ?? 0 : o.Card?.Damage ?? 0).FirstOrDefault()
                        : preferred;
                }""")
    edit(quality, "                    key = RouteKey(roll.End);", '''                    using var routeTiming = _meter?.Measure("win_dedup_and_output");
                    key = RouteKey(roll.End);''')
    edit(quality, "                Keep(anchors.Append(_root));", "                Keep(retained ?? anchors.Append(_root));")

    program = src / "Program.cs"
    edit(program, '                if (kind == "b1b_fault_delay")', """                if (kind == "f6_wire")
                    result = new() { ["type"] = "f6_wire", ["value"] = _f6Wire };
                else if (kind == "b1b_fault_delay")""")
    edit(program, "    static void WriteLine(Dictionary<string, object?> data)",
         "    private static object? _f6Wire;\n\n    static void WriteLine(Dictionary<string, object?> data)")
    edit(program, "        Console.Out.WriteLine(JsonSerializer.Serialize(data, JsonOpts));",
         """        if (data.ContainsKey("f6_profile"))
        {
            long started = System.Diagnostics.Stopwatch.GetTimestamp();
            string json = JsonSerializer.Serialize(data, JsonOpts);
            double serializeMs = System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMilliseconds;
            started = System.Diagnostics.Stopwatch.GetTimestamp();
            Console.Out.WriteLine(json);
            Console.Out.Flush();
            _f6Wire = new { serialize_ms = serializeMs,
                write_ms = System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMilliseconds,
                chars = json.Length };
            return;
        }
        Console.Out.WriteLine(JsonSerializer.Serialize(data, JsonOpts));""")


if __name__ == "__main__":
    b1b.b1a.i1.build(b1b.b1a.ROOT / "logs/m1-f6a-build", stage)
