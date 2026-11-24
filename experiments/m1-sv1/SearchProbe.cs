using System.Diagnostics;
using MegaCrit.Sts2.Core.Entities.Players;

namespace CombatSolver.Engine.InCombat.Simulation;

// Active only inside an SV1 branch. Historical replay uses the normal solver.
internal sealed class SearchProbe(bool guard) : IDisposable
{
    [ThreadStatic] private static SearchProbe? _current;
    internal string? Boundary { get; private set; }
    internal object? Draw { get; private set; }
    internal long ForkTicks { get; private set; }
    internal int Forks { get; private set; }
    private bool Guard => guard;

    internal SearchProbe Enter()
    {
        if (_current != null) throw new InvalidOperationException("Nested SV1 probe");
        _current = this;
        return this;
    }

    public void Dispose() => _current = null;

    internal static void Stop(string reason)
    {
        if (_current is not { Guard: true } probe) return;
        probe.Boundary ??= reason;
        throw new BoundaryException(reason);
    }

    internal static void BeforeDraw(CombatPredictionSimulator sim, Player player, int remaining, bool handDraw)
    {
        if (_current is not { Guard: true } probe) return;
        var state = sim.State.GetPlayerCombatState(player);
        probe.Draw ??= new
        {
            remaining, hand_draw = handDraw, hand_count = state.Hand.Cards.Count,
            draw_count = state.DrawPile.Cards.Count, discard_count = state.DiscardPile.Cards.Count,
            round = sim.State.CombatState.RoundNumber,
        };
        Stop("unknown_draw");
    }

    internal static ForkTimer MeasureFork() => new(_current);

    internal readonly struct ForkTimer(SearchProbe? probe) : IDisposable
    {
        private readonly long _start = probe == null ? 0 : Stopwatch.GetTimestamp();
        public void Dispose()
        {
            if (probe == null) return;
            probe.Forks++;
            probe.ForkTicks += Stopwatch.GetTimestamp() - _start;
        }
    }

    private sealed class BoundaryException(string reason) : Exception(reason);
}
