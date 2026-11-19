"""Stage a synthetic host with the P1 settled-map retirement boundary."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("b1a_f4_build", HERE.parent / "m1-f4/build.py")
f4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f4)
i1 = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.f1.i1
edit = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.replace


def stage(src):
    f4.stage(src)
    p1 = (ROOT / "scripts/m1_p1/HotWorkerProbe.cs").read_text(encoding="utf-8")
    # Reuse the reset and exclusive timing scopes, not the P1 protocol.
    p1 = p1[:p1.index("\npartial class Program")]
    (src / "RootWorker.cs").write_text(p1, encoding="utf-8")
    sim = src / "RunSimulator.cs"
    edit(sim, "    private bool _executing;", "    private bool _executing;\n"
         "    internal bool ProbeIdle => !_executing && _queue.Count == 0;")
    synthetic = src / "SyntheticCombat.cs"
    edit(synthetic, "        EnsureModelDbInitialized();", '''        using (ProbeTiming.Begin("model_init"))
            EnsureModelDbInitialized();
        using var build = ProbeTiming.Begin("native_build");
        _initialProgress ??= ProbeProgress();''')
    edit(synthetic, "_ => _turnStarted.Set();", "ProbeTurnStarted;")
    edit(synthetic, "_ => _combatEnded.Set();", "ProbeCombatEnded;")
    edit(synthetic, "        var spec = request.GetProperty", '''        SyntheticCombatSpec? spec;
        using (ProbeTiming.Begin("input_parse"))
            spec = request.GetProperty''')
    program = src / "Program.cs"
    edit(program, "var sim = new RunSimulator();", "ProbeTiming.ProtocolThread = Environment.CurrentManagedThreadId;\n"
         "        var sim = new RunSimulator();")
    edit(program, '                if (kind == "synthetic_catalog")', '''                if (kind == "b1a_reset")
                {
                    sim.ProbeReset();
                    RunSimulator.ProbeRestoreProgress();
                    sim = new RunSimulator();
                    result = new() { ["type"] = "reset" };
                }
                else if (kind == "b1a_profile")
                    result = new() { ["type"] = "profile", ["value"] = RunSimulator.ProbeProgress() };
                else if (kind == "synthetic_catalog")''')
    edit(program, 'or "skip_select" or "use_potion"', 'or "skip_select" or "use_potion" or "skip_card_reward"')
    edit(program, "                WriteLine(result);", '''                result["_b1a_ms"] = ProbeTiming.Take();
                WriteLine(result);''')


if __name__ == "__main__":
    i1.build(ROOT / "logs/m1-b1a-build", stage)
