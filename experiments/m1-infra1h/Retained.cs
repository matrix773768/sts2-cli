using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private readonly Dictionary<string,(SimulationSnapshot Snapshot,PileLaw Law)> retained = new();
    private void Retire(string key)
    {
        var entry=referencePrefixes[key];
        if(retained.Remove(key,out var duplicate))duplicate.Snapshot.ReleaseSimulator();
        if(retained.Count>=256)
        {
            var oldest=retained.Keys.First();
            retained[oldest].Snapshot.ReleaseSimulator();
            retained.Remove(oldest);
        }
        retained.Add(key,entry);
    }
    private void ClearRetained()
    {
        foreach(var entry in retained.Values)entry.Snapshot.ReleaseSimulator();
        retained.Clear();
    }
}
