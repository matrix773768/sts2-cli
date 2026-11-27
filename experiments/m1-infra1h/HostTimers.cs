using System.Diagnostics;
using System.Text.Json;

namespace Sts2Headless;
internal static class HostTimers
{
    internal static readonly bool Enabled=Environment.GetEnvironmentVariable("INFRA1H_TIMERS")=="1";
    internal static long Reference,HotWindow,HotAction,LegacyStep,Fork,Bind,Conditional,Fifo,PeakSamples;
    internal readonly ref struct Timer
    {
        private readonly ref long destination;
        private readonly long start;
        internal Timer(ref long value){destination=ref value;start=Enabled?Stopwatch.GetTimestamp():0;}
        public void Dispose(){if(Enabled)destination+=Stopwatch.GetTimestamp()-start;}
    }
    static HostTimers()
    {
        if(Enabled)AppDomain.CurrentDomain.ProcessExit+=(_,_)=>File.WriteAllText("infra1h-timers.json",
            JsonSerializer.Serialize(new{Reference,HotWindow,HotAction,LegacyStep,Fork,Bind,Conditional,Fifo,PeakSamples,frequency=Stopwatch.Frequency}));
    }
}
