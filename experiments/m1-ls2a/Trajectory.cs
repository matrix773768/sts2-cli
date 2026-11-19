using System.Diagnostics;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    internal object RunTrajectory(string strategy)
    {
        if (!Strategies.Contains(strategy))
            throw new ArgumentException("Unknown frozen trajectory policy", nameof(strategy));

        _watch.Start();
        var result = Rollout(new(new(strategy, [], null, "initial"), _root));
        _watch.Stop();
        if (Digest(_root.State!) != _root.Frame.Stamp)
            throw new InvalidOperationException("Trajectory mutated its source");
        var end = result.End.Frame;
        return new
        {
            strategy, status = result.Stop, detail = result.Detail,
            transitions = _used, hot_ms = _watch.Elapsed.TotalMilliseconds, replay_ms = _replayMs,
            peak_working_set_bytes = Process.GetCurrentProcess().PeakWorkingSet64,
            cap = _cap, root_stamp = _root.Frame.Stamp, root_unchanged = true,
            resource = new { end.Hp, end.MaxHp, end.Gold, end.Potions, hp_lost = end.CumulativeLoss },
            actions = Path(result.End).Skip(1).Select(n => n.Option!.Action).ToArray(),
            end.Boundary, end.Gaps
        };
    }
}
