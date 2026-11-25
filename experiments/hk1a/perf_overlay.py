"""Prepare a diagnostics-only Harness without rebuilding or editing the frozen Solver."""
import argparse
from pathlib import Path
import subprocess
import os
import zipfile
import json

from hk1a_build import ARCHIVE_SHA, PIN, ROOT, checksum, recipe_source


def edit(path, before, after):
    source = path.read_text(encoding="utf-8")
    if source.count(before) != 1:
        raise ValueError(f"Unexpected source anchor in {path}: {before}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def build(out, archive, steam, original):
    if checksum(archive) != ARCHIVE_SHA:
        raise ValueError("Wrong upstream source archive")
    out.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as src:
        src.extractall(out)
    tree = out / f"CombatSolver-{PIN}"
    harness = tree / "tools/search/OfflineSearchHarness"
    (harness / "Hk1Root.cs").write_text(recipe_source(), encoding="utf-8")
    oracle = harness / "Oracle.cs"
    oracle.write_bytes(Path(__file__).with_name("Oracle.cs").read_bytes())
    edit(harness / "Program.cs", '        if (rawArgs.Length == 1 && rawArgs[0] is "--help" or "-h")',
         '        if (rawArgs.Length == 6 && rawArgs[0] == "--hk1a")\n'
         '            return Hk1Oracle.Run(rawArgs[1..]);\n'
         '        if (rawArgs.Length == 1 && rawArgs[0] is "--help" or "-h")')
    edit(oracle, 'BudgetMilliseconds = int.Parse(args[3]), MaxDegreeOfParallelism = 1,',
         '''BudgetMilliseconds = int.Parse(args[3]),
            MaxDegreeOfParallelism = int.Parse(Environment.GetEnvironmentVariable("HKPERF_DOP") ?? "1"),
            MaxCardBranchesPerNode = int.Parse(Environment.GetEnvironmentVariable("HKPERF_BRANCHES") ?? "32"),
            Nodes = int.Parse(Environment.GetEnvironmentVariable("HKPERF_NODES") ?? "150000"),
            MeasureSearchPhases = true,''')
    edit(oracle, 'Profile = "Custom", Beam = 96, Nodes = 150000,', 'Profile = "Custom", Beam = 96,')
    edit(oracle, 'var found = ModRuntime.RunSearchDetailed(combat, options, loop, null);',
         '''var proc = Process.GetCurrentProcess();
            var cpuBefore = proc.TotalProcessorTime;
            int[] gcBefore = [GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2)];
            long before = GC.GetTotalAllocatedBytes(true);
            var found = ModRuntime.RunSearchDetailed(combat, options, loop, null);
            proc.Refresh();
            var perf = new { cpuMs = (proc.TotalProcessorTime - cpuBefore).TotalMilliseconds,
                peakBytes = proc.PeakWorkingSet64, allocated = GC.GetTotalAllocatedBytes(true) - before,
                gc = gcBefore.Select((count, generation) => GC.CollectionCount(generation) - count).ToArray(),
                runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                clr = typeof(object).Assembly.Location, processors = Environment.ProcessorCount,
                solver = typeof(HotKernelChecks).Assembly.Location,
                solverDll = typeof(HotCombatEngine).Assembly.Location };''')
    edit(oracle, 'result = new { identity, init, route, search = found.LegacyMetrics, found.WallSeconds,',
         'result = new { identity, init, route, policy = found.Policy, perf, search = found.LegacyMetrics, found.WallSeconds,')

    checks = harness / "HotKernelChecks.cs"
    text = checks.read_text(encoding="utf-8")
    start = text.index("            for (int i = 0; i < 1000; i++)", text.index("using PackedStateArena arena", text.index("private static int RunGateC")))
    text = text[:start] + text[start:].replace(
        "            for (int i = 0; i < 1000; i++)",
        '''            int warm = int.Parse(Environment.GetEnvironmentVariable("HKPERF_WARM") ?? "1000");
            bool phase = Environment.GetEnvironmentVariable("HKPERF_PHASE") == "1";
            for (int i = 0; i < warm; i++)''', 1)
    cursor = text.index("            hotSw.Stop();", start)
    text = text[:cursor] + text[cursor:].replace(
        "            hotSw.Stop();",
        """            hotSw.Stop();
            if (phase)
            {
                long unpackTicks = 0, stepTicks = 0, packTicks = 0, hashTicks = 0, copyTicks = 0, timerTicks = 0;
                ulong mix = 1;
                for (int i = 0; i < hotIters; i++)
                {
                    long a = Stopwatch.GetTimestamp();
                    long b = Stopwatch.GetTimestamp();
                    timerTicks += b - a;
                    HotStatePacker.Unpack(arena.GetSpan(rootHandle), ref workState);
                    long c = Stopwatch.GetTimestamp();
                    HotColdSidecar? wc = rootCold;
                    var executed = HotCombatEngine.Step(ref workState, ref wc, bundle.Rules, scratch, hotAction);
                    long d = Stopwatch.GetTimestamp();
                    int len = HotStatePacker.Pack(ref workState, ref wc, packBuf, canonicalize: true);
                    long e = Stopwatch.GetTimestamp();
                    mix = unchecked(mix * 31 + HotHash.ComputeHash(packBuf.AsSpan(0, len), wc).Lo);
                    long f = Stopwatch.GetTimestamp();
                    CombatHotState copy = workState;
                    long g = Stopwatch.GetTimestamp();
                    if (!executed.Executed) throw new InvalidOperationException("Gate action did not execute");
                    mix = ConsumeCopy(in copy, mix);
                    unpackTicks += c - b; stepTicks += d - c; packTicks += e - d;
                    hashTicks += f - e; copyTicks += g - f;
                }
                double Ns(long ticks) => ticks * 1e9 / Stopwatch.Frequency / hotIters;
                Console.WriteLine($"HKPERF phase_ns timer={Ns(timerTicks):F0} unpack={Ns(unpackTicks):F0} step={Ns(stepTicks):F0} pack={Ns(packTicks):F0} hash={Ns(hashTicks):F0} copy={Ns(copyTicks):F0} cold={rootCold != null} sink={mix:X16}");
            }""", 1)
    point = text.rfind("}")
    text = text[:point] + """
    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static ulong ConsumeCopy(in CombatHotState state, ulong seed)
        => unchecked(seed * 31 + (uint)(state.Player.CurrentHp + state.Player.Block + state.HandCount));
""" + text[point:]
    checks.write_text(text, encoding="utf-8")
    config = Path(original["dll"]).with_suffix(".runtimeconfig.json")
    solver = json.loads(config.read_text(encoding="utf-8"))["runtimeOptions"]["configProperties"]["CombatSolverDll"]
    env = os.environ | {"NUGET_PACKAGES": str(ROOT / "logs/nuget-packages"),
                        "DOTNET_CLI_HOME": str(out / "dotnet-home"),
                        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    project = harness / "OfflineSearchHarness.csproj"
    with (out / "build.log").open("wb") as log:
        subprocess.run(["dotnet", "build", str(project), "-c", "Release", "-m:1",
                        "-p:UseSharedCompilation=false", "-p:NuGetAudit=false",
                        f"-p:SteamRoot={steam}", f"-p:CombatSolverDll={solver}"],
                       cwd=tree, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    dll = next((tree / ".local/tool-build/OfflineSearchHarness/bin").rglob("OfflineSearchHarness.dll"))
    return original | {"dll": str(dll), "tree": str(tree), "version": "hk1a-perf-overlay",
                       "overlay_sha256": checksum(dll), "solver_path": str(Path(solver).resolve()),
                       "solver_sha256": checksum(Path(solver))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads((ROOT / "logs/hk1a-final-build/build.json").read_text(encoding="utf-8"))
    out = args.output.resolve()
    result = build(out, args.archive.resolve(), args.steam.resolve(), original)
    (out / "build.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
