namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    internal bool Adaptive { private get; set; }

    private string[] InitialStrategies()
    {
        if (!Adaptive)
            return Strategies;

        var menu = Menu(_root);
        int threat = Threat(_root);
        if (threat >= Math.Max(1, _root.Frame.Hp - 3) && menu.Any(o => o.Card?.Block > 0))
            return ["DEFENSIVE", "Q1", "AGGRO", "ENGINE"];
        if (threat <= 3 && menu.Any(EngineCard))
            return ["ENGINE", "Q1", "AGGRO", "DEFENSIVE"];
        return Strategies;
    }

    private bool StopQuality(int bestHp, int dryAttempts, int dryTransitions)
    {
        // Root HP is the recovery target for this restricted no-growth experiment.
        // This is an opportunity-cost heuristic, not an upper bound on HP.
        if (bestHp >= _root.Frame.Hp)
            _limit = "adaptive_recovered_entry_hp";
        else if (dryAttempts >= 4 && dryTransitions >= 48)
            _limit = "adaptive_plateau";
        return _limit is not null;
    }
}
