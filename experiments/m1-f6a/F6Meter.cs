using System.Diagnostics;
using System.Reflection;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed class F6Meter
{
    private static readonly FieldInfo RunField = typeof(CombatBeamSolver)
        .GetField("_run", BindingFlags.Instance | BindingFlags.NonPublic)!;

    private readonly Dictionary<string, (long Ticks, long Bytes, int Count)> _samples = new();

    public IDisposable Measure(string name) => new Scope(this, name);

    // Nested adapter scopes are inclusive. Solver phase scopes are exclusive.
    public object Snapshot() => _samples.ToDictionary(p => p.Key, p => new {
        ms = Stopwatch.GetElapsedTime(0, p.Value.Ticks).TotalMilliseconds,
        allocated_bytes = p.Value.Bytes, count = p.Value.Count
    });

    public static (object Phases, int Forks) Solver(CombatBeamSolver solver)
    {
        object run = RunField.GetValue(solver)!;
        Type type = run.GetType();
        var performance = (SearchPerformanceMetrics)type.GetField("Performance")!.GetValue(run)!;
        int forks = (int)type.GetField("ForkCount")!.GetValue(run)!;
        var phases = Enum.GetValues<SearchMetricPhase>().ToDictionary(phase => phase.ToString(), phase => {
            var value = performance.Snapshot(phase);
            return new { ms = value.Elapsed.TotalMilliseconds, allocated_bytes = value.AllocatedBytes };
        });
        return (phases, forks);
    }

    private sealed class Scope(F6Meter meter, string name) : IDisposable
    {
        private readonly long _started = Stopwatch.GetTimestamp();
        private readonly long _bytes = GC.GetAllocatedBytesForCurrentThread();

        public void Dispose()
        {
            var (ticks, bytes, count) = meter._samples.GetValueOrDefault(name);
            meter._samples[name] = (ticks + Stopwatch.GetTimestamp() - _started,
                bytes + GC.GetAllocatedBytesForCurrentThread() - _bytes, count + 1);
        }
    }
}
