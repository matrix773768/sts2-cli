"""Stage opt-in F5B variants alongside the unchanged F3B C and F4 defaults."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f5b_f4", HERE.parent / "m1-f4/build.py")
f4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f4)
i1 = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.f1.i1
edit = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.replace


def stage(src):
    f4.stage(src)
    (src / "AdaptiveSearch.cs").write_bytes((HERE / "AdaptiveSearch.cs").read_bytes())
    edit(src / "Host.cs", '        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]',
         '''        search.Adaptive = request.TryGetProperty("f5b_adaptive", out var adaptive) && adaptive.GetBoolean();
        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]''')
    routes = src / "RouteSearch.cs"
    edit(routes, 'arm == "A" ? ["Q1"] : Strategies', 'arm == "A" ? ["Q1"] : InitialStrategies()')
    edit(routes, '                Option? Original(Node n)', '''                if (Adaptive && failure is { SurvivalGap: > 0 })
                {
                    Add(late, task.Plan.Strategy, id, "turn_window",
                        new(late.Frame.Stamp, "critical_window", null, targeted, focus, 3));
                }
                Option? Original(Node n)''')
    quality = src / "QualitySearch.cs"
    edit(quality, '        foreach (string strategy', '''        int bestHp = incumbent.Frame.Hp;
        int dryAttempts = 0, lastGain = _used;
        foreach (string strategy''')
    edit(quality, '                if (!Continue()) return;', '''                if (!Continue()) return;
                if (Adaptive && StopQuality(bestHp, dryAttempts, _used - lastGain))
                    return;''')
    edit(quality, '                string? key = null;', '''                dryAttempts++;
                if (roll.Stop == "predicted_win" && roll.End.Frame.Hp > bestHp
                    && roll.End.Frame.Potions.SequenceEqual(incumbent.Frame.Potions))
                {
                    bestHp = roll.End.Frame.Hp;
                    lastGain = _used;
                    dryAttempts = 0;
                }
                string? key = null;''')


if __name__ == "__main__":
    i1.build(i1.ROOT / "logs/m1-f5b-build", stage)
