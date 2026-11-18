using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;

namespace Sts2Headless;

public partial class RunSimulator
{
    internal Dictionary<string, object?> ExecuteF1Action(Player player, ICardSelector choices,
        string action, Dictionary<string, object?> args)
    {
        _cardSelectorScope?.Dispose();
        var stack = RunManager.Instance.CardSelectorStack;
        try
        {
            using var scope = stack.UseSelector(player, choices);
            return ExecuteAction(action, args);
        }
        finally
        {
            _cardSelectorScope = stack.UseSelector(player, _cardSelector);
        }
    }
}
