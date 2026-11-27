namespace CombatSolver.HotKernel;

internal static class InfraCObserver
{
    internal delegate void Capture(in CombatHotState state, HotColdSidecar? cold, HotRules rules, int draw);
    [ThreadStatic] internal static Capture? BeforeDraw;
}
