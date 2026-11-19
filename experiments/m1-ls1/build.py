"""Stage an isolated opt-in scheduler seam over the frozen S3A/B1B host."""
import runpy

from ls1_design import HERE, ROOT

base = runpy.run_path(str(HERE.parent / "m1-s3a/build_host.py"))
edit = base["edit"]
i1 = base["b1b"].b1a.i1


def stage(src):
    base["stage"](src)
    routes = src / "RouteSearch.cs"
    edit(routes, "    private readonly List<object> _routes = [];", """    private readonly List<object> _routes = [];
    private string[]? _ls1Order;
    private bool _ls1Probe;

    internal void ConfigureLs1(JsonElement request, string arm)
    {
        bool hasOrder = request.TryGetProperty("ls1_order", out var order);
        bool probe = request.TryGetProperty("ls1_probe", out var candidate);
        if (!hasOrder && !probe) return;
        if (request.GetProperty("cmd").GetString() != "i1_f3b" || arm != "C" ||
            request.TryGetProperty("f5b_adaptive", out _) || request.TryGetProperty("repair_probe", out _) ||
            hasOrder == probe)
            throw new ArgumentException("Expected one LS1 research override for F3B C");

        if (probe)
        {
            string? strategy = candidate.GetString();
            if (strategy == null || !Strategies.Contains(strategy))
                throw new ArgumentException("Unknown LS1 probe candidate");
            _ls1Order = [strategy];
            _ls1Probe = true;
            return;
        }

        var ordered = order.EnumerateArray().Select(item => item.GetString() ?? "").ToArray();
        if (ordered.Length != Strategies.Length || !ordered.ToHashSet().SetEquals(Strategies))
            throw new ArgumentException("LS1 order must be an exact permutation of frozen candidates");
        _ls1Order = ordered;
    }""")
    edit(routes, 'arm == "A" ? ["Q1"] : Strategies',
         'arm == "A" ? ["Q1"] : _ls1Order ?? Strategies')
    edit(routes, 'if (arm != "A" && roll.Stop == "death"', 'if (!_ls1Probe && arm != "A" && roll.Stop == "death"')
    edit(src / "Host.cs", '        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]',
         '        search.ConfigureLs1(request, arm);\n        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]')
    quality = src / "QualitySearch.cs"
    edit(quality, "        int seedTransitions = 0;", """        int seedTransitions = 0;
        double? seedLockMs = null;""")
    edit(quality, '                Improve(Path(current), attempts, wins);', '''            {
                seedLockMs = _watch.Elapsed.TotalMilliseconds;
                Improve(Path(current), attempts, wins);
            }''')
    edit(quality, "            seed_transitions = seedTransitions,",
         "            seed_lock_ms = seedLockMs, seed_verified = seedLockMs.HasValue, seed_transitions = seedTransitions,")
    # The driver only opens a pinned, read-only F3A checkpoint and its recorded room entry.
    # All writes, fresh runs and arbitrary room construction remain blocked in this host.
    program = src / "Program.cs"
    edit(program, '"start_run" or "load_save" or "write_continue_save"', '"start_run" or "write_continue_save"')
    edit(program, 'or "skip_card_reward"))', 'or "skip_card_reward" or "select_map_node"))')


if __name__ == "__main__":
    i1.build(ROOT / "logs/m1-ls1-build", stage)
