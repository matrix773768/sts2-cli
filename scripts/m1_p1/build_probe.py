"""Build an instrumented copy. The production assembly and sources stay untouched."""
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "src/Sts2Headless"
BUILD = ROOT / "logs/m1-p1/build"


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError(f"Unexpected source shape for {old!r}: {text.count(old)}")
    return text.replace(old, new)


def scope(text, method, phase):
    start = text.index(method)
    body = text.index("\n    {\n", start) + len("\n    {\n")
    return text[:body] + f'        using var phase = ProbeTiming.Begin("{phase}");\n' + text[body:]


def build():
    BUILD.mkdir(parents=True, exist_ok=True)
    stubs = BUILD.parent / "GodotStubs"
    stubs.mkdir(exist_ok=True)
    for source in (ROOT / "src/GodotStubs").iterdir():
        if source.suffix in {".cs", ".csproj"}:
            shutil.copyfile(source, stubs / source.name)
    project = (SOURCE / "Sts2Headless.csproj").read_text(encoding="utf-8")
    project = replace(project, "..\\..\\lib\\", str(ROOT / "lib") + "/", 8)
    (BUILD / "Sts2Headless.csproj").write_text(project, encoding="utf-8")
    shutil.copyfile(HERE / "HotWorkerProbe.cs", BUILD / "HotWorkerProbe.cs")

    sim = (SOURCE / "RunSimulator.cs").read_text(encoding="utf-8")
    sim = replace(sim, "public class RunSimulator", "public partial class RunSimulator")
    sim = replace(sim, "    private bool _executing;", "    private bool _executing;\n"
                  "    internal bool ProbeIdle => !_executing && _queue.Count == 0;")
    sim = replace(sim, "_ => _turnStarted.Set();", "ProbeTurnStarted;", 2)
    sim = replace(sim, "_ => _combatEnded.Set();", "ProbeCombatEnded;", 2)
    for method, phase in (
        ("public Dictionary<string, object?> LoadSave(", "load_other"),
        ("private static void EnsureModelDbInitialized(", "model_init"),
        ("public Dictionary<string, object?> ExecuteAction(", "action_other"),
        ("private Dictionary<string, object?> DetectDecisionPoint(", "decision"),
        ("private Dictionary<string, object?> DetectPostCombatState(", "reward_processing"),
        ("public Dictionary<string, object?> GetFullMap(", "map"),
        ("private void WaitForActionExecutor(", "wait_and_pump"),
        ("private void SpinWaitForCombatStable(", "wait_and_pump"),
        ("public void Pump(", "wait_and_pump"),
        ("public void CleanUp(", "native_cleanup"),
        ("public Dictionary<string, object?> SaveCheckpoint(", "save"),
    ):
        sim = scope(sim, method, phase)
    sim = replace(sim, "var readResult = SaveManager.FromJson<SerializableRun>(saveJson);",
                  'var readResult = ProbeTiming.Measure("deserialize", () => SaveManager.FromJson<SerializableRun>(saveJson));')
    sim = replace(sim, "_runState = RunState.FromSerializable(save);",
                  'using (ProbeTiming.Begin("runstate")) _runState = RunState.FromSerializable(save);')
    sim = replace(sim, 'RunManager.Instance.SetUpSavedSingleplayer(_runState, save).GetAwaiter().GetResult();',
                  '_initialProgress ??= ProbeProgress();\n'
                  '            RunManager.Instance.SetUpSavedSingleplayer(_runState, save).GetAwaiter().GetResult();')
    sim = replace(sim, "var deadline = Environment.TickCount64 + 5000;",
                  'using var waiting = ProbeTiming.Begin("wait_and_pump");\n'
                  '            var deadline = Environment.TickCount64 + 5000;')
    sim = replace(sim, "RunManager.Instance.SetUpSavedSingleplayer(_runState, save).GetAwaiter().GetResult();",
                  'using (ProbeTiming.Begin("setup_saved"))\n'
                  '                RunManager.Instance.SetUpSavedSingleplayer(_runState, save).GetAwaiter().GetResult();')
    sim = replace(sim, "RunManager.Instance.EnterAct(_runState.CurrentActIndex, doTransition: false).GetAwaiter().GetResult();",
                  'using (ProbeTiming.Begin("enter_act"))\n'
                  '                    RunManager.Instance.EnterAct(_runState.CurrentActIndex, doTransition: false).GetAwaiter().GetResult();')
    (BUILD / "RunSimulator.cs").write_text(sim, encoding="utf-8")

    program = (SOURCE / "Program.cs").read_text(encoding="utf-8")
    program = replace(program, "class Program", "partial class Program")
    program = replace(program, "var sim = new RunSimulator();",
                      "ProbeTiming.ProtocolThread = Environment.CurrentManagedThreadId;\n"
                      "        var sim = new RunSimulator();")
    program = replace(program, "result = HandleCommand(sim, cmd);", """switch (cmd.GetProperty("cmd").GetString())
                {
                    case "probe_reset":
                        sim.ProbeReset();
                        RunSimulator.ProbeRestoreProgress();
                        sim = new RunSimulator();
                        result = new() { ["type"] = "reset" };
                        break;
                    case "probe_rng":
                        result = new() { ["type"] = "rng", ["value"] = sim.ProbeRng() };
                        break;
                    case "probe_progress":
                        result = new() { ["type"] = "progress", ["value"] = RunSimulator.ProbeProgress() };
                        break;
                    case "probe_batch":
                        result = ProbeBatch(sim, cmd.GetProperty("actions"));
                        break;
                    case "probe_timeout":
                        Thread.Sleep(Timeout.Infinite);
                        throw new InvalidOperationException("Timeout injection returned");
                    default:
                        result = HandleCommand(sim, cmd);
                        break;
                }""")
    program = replace(program, "                WriteLine(result);",
                      '                result["_probe_ms"] = ProbeTiming.Take();\n'
                      '                WriteLine(result);')
    (BUILD / "Program.cs").write_text(program, encoding="utf-8")
    subprocess.run(["dotnet", "build", str(BUILD / "Sts2Headless.csproj"), "--nologo"],
                   cwd=ROOT, check=True)


if __name__ == "__main__":
    build()
