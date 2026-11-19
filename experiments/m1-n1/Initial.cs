using System;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    internal object RunInitial(string strategy)
    {
        if (!Strategies.Contains(strategy) && strategy is not ("THREAT_V1" or "DURABLE_V1"))
            throw new ArgumentException("Unknown initial strategy", nameof(strategy));

        _watch.Start();
        var result = Rollout(new(new(strategy, [], null, "initial"), _root));
        _watch.Stop();
        if (Digest(_root.State!) != _root.Frame.Stamp)
            throw new InvalidOperationException("Initial rollout mutated its root");

        return new
        {
            strategy,
            status = result.Stop,
            detail = result.Detail,
            transitions = _used,
            hot_ms = _watch.Elapsed.TotalMilliseconds,
            action_count = result.End.Depth,
            start = _root.Frame,
            end = result.End.Frame,
            history = _history,
            transition_faults = _transitionFaults,
        };
    }
}
