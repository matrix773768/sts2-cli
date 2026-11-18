"""Stage a profiling-only variant of the F3B host without changing its responses."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("d1_meter_f3b", HERE.parent / "m1-f3b/build.py")
f3b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3b)


def stage(source):
    f3b.stage(source)
    edit = f3b.f3a.f2.replace
    program = source / "Program.cs"
    edit(program, "            Dictionary<string, object?>? result;", """            var dispatchStarted = System.Diagnostics.Stopwatch.GetTimestamp();
            var meterCommand = "unknown";
            RunSimulator.D1PublicCombatMs = 0;
            Dictionary<string, object?>? result;""")
    edit(program, "                var cmd = JsonSerializer.Deserialize<JsonElement>(line);",
         """                var cmd = JsonSerializer.Deserialize<JsonElement>(line);
                if (cmd.TryGetProperty("cmd", out var meterName))
                    meterCommand = meterName.GetString() ?? "unknown";""")
    edit(program, "                WriteLine(result);", """                var dispatchMs = System.Diagnostics.Stopwatch.GetElapsedTime(dispatchStarted).TotalMilliseconds;
                var serializeStarted = System.Diagnostics.Stopwatch.GetTimestamp();
                var wire = JsonSerializer.Serialize(result, JsonOpts);
                var serializeMs = System.Diagnostics.Stopwatch.GetElapsedTime(serializeStarted).TotalMilliseconds;
                var emitStarted = System.Diagnostics.Stopwatch.GetTimestamp();
                Console.Out.WriteLine(wire);
                Console.Out.Flush();
                var emitMs = System.Diagnostics.Stopwatch.GetElapsedTime(emitStarted).TotalMilliseconds;
                Console.Error.WriteLine(FormattableString.Invariant(
                    $"[D1_TIMING] {meterCommand} {dispatchMs:R} {RunSimulator.D1PublicCombatMs:R} {serializeMs:R} {emitMs:R}"));""")
    edit(source / "RunSimulator.cs", "    private Dictionary<string, object?> CombatPlayState(Player player)",
         """    [ThreadStatic] internal static double D1PublicCombatMs;

    private Dictionary<string, object?> CombatPlayState(Player player)
    {
        var started = System.Diagnostics.Stopwatch.GetTimestamp();
        try { return D1BuildCombatPlayState(player); }
        finally { D1PublicCombatMs += System.Diagnostics.Stopwatch.GetElapsedTime(started).TotalMilliseconds; }
    }

    private Dictionary<string, object?> D1BuildCombatPlayState(Player player)""")


if __name__ == "__main__":
    f1 = f3b.f3a.f2.f1
    f1.i1.build(f1.i1.ROOT / "logs/m1-d1-meter-build", stage)
