using System.Diagnostics;
using System.Text.Json;

internal static class InfraMeter
{
    internal static long Now => Stopwatch.GetTimestamp();
    private static readonly Dictionary<string, long> values = new();
    private static string command = "startup";
    private static readonly Process process = Process.GetCurrentProcess();
    private static long origin;
    private static readonly List<object> jit = new();
    internal static void Warmup(string stage) {
        jit.Add(new { stage, ticks = Now, methods = System.Runtime.JitInfo.GetCompiledMethodCount(),
            il_bytes = System.Runtime.JitInfo.GetCompiledILBytes(),
            compilation_seconds = System.Runtime.JitInfo.GetCompilationTime().TotalSeconds });
    }
    internal static void Start() { origin = Now; }
    internal static void Parsed(string name) {
        command = name;
        Add("parse_ticks", Now - origin);
        Add("requests", 1);
        origin = Now;
    }
    internal static void Handled() {
        Add("handle_ticks", Now - origin);
        if (command == "pre0_abandon") Warmup("retire");
    }
    internal static void Add(string name, long count) {
        string key = command + "/" + name;
        values[key] = values.GetValueOrDefault(key) + count;
    }
    internal static void Step(string name, Action action) {
        long start = Now;
        try { action(); }
        finally { Add(name + "_ticks", Now - start); Add(name + "_count", 1); }
    }
    internal static T Measure<T>(string name, Func<T> action) {
        long start = Now;
        try { return action(); }
        finally { Add(name + "_ticks", Now - start); Add(name + "_count", 1); }
    }
    internal static void Save() {
        Warmup("exit");
        process.Refresh();
        File.WriteAllText("infra-host.json", JsonSerializer.Serialize(new {
            frequency = Stopwatch.Frequency, values, jit,
            cpu_seconds = process.TotalProcessorTime.TotalSeconds,
            peak_working_set = process.PeakWorkingSet64,
            gc = new [] { GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2) }
        }));
    }
}
