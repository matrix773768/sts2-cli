namespace CombatSolver;

internal sealed partial class CombatBeamSolver
{
    private static readonly string? RankingExperiment = Environment.GetEnvironmentVariable("M1L3_RANK");
    private static readonly StateFingerprint CrawlersParent = new(4794595152587844184, 13933205124396862950);
    private static readonly StateFingerprint CrawlersStrike = new(17081539879745055099, 6157755496321621557);
    private static readonly StateFingerprint CrawlersDefend = new(1355609195813973648, 11553611504259844353);
    private bool _rankingPoolObserved;
    private int _rankingBestLoss = int.MaxValue;

    private void ApplyRankingExperiment(List<SearchNode> retained)
    {
        if (RankingExperiment == null || _rankingPoolObserved)
            return;
        int strike = -1, defend = -1;
        for (int i = 0; i < retained.Count; i++)
        {
            var child = retained[i];
            if (child.ActionCount != 1 || child.Parent?.StateKey != CrawlersParent)
                continue;
            if (child.StateKey == CrawlersStrike && child.Action is { CardId: "STRIKE_IRONCLAD", TargetCombatId: 1 })
                strike = i;
            if (child.StateKey == CrawlersDefend && child.Action is { CardId: "DEFEND_IRONCLAD" })
                defend = i;
        }
        if (strike < 0 || defend < 0)
            return;
        _rankingPoolObserved = true;
        Console.WriteLine($"L3_POOL {_run.Expanded} {strike} {defend} {retained.Count}");
        if ((RankingExperiment == "strike" && strike > defend)
            || (RankingExperiment == "defend" && defend > strike))
        {
            (retained[strike], retained[defend]) = (retained[defend], retained[strike]);
            Console.WriteLine($"L3_SWAP {defend} {strike}");
        }
    }

    private void ObserveRankingExpansion(SearchNode node)
    {
        if (RankingExperiment == null || _run.Expanded > 12)
            return;
        Console.WriteLine($"L3_EXPAND {_run.Expanded} {node.StateKey.First} {node.StateKey.Second}");
    }

    private void ObserveRankingVictory(SearchNode node, long milliseconds)
    {
        if (RankingExperiment == null || !node.Snapshot.AllEnemiesDead || node.Snapshot.PlayerDead
            || node.HasPredictionRisk || node.Snapshot.BoundaryReason != SearchBoundaryReason.None
            || node.Snapshot.CumulativePlayerHpLost >= _rankingBestLoss)
            return;
        _rankingBestLoss = node.Snapshot.CumulativePlayerHpLost;
        Console.WriteLine($"L3_WIN {_run.Expanded} {_run.TransitionCount} {milliseconds} {_rankingBestLoss} {node.Turn}");
    }
}
