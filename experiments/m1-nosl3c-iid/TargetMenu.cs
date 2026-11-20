using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;

namespace OfflineSearchHarness;

internal static class TargetMenu
{
    internal static bool Manual(TargetType type) =>
        type is TargetType.AnyEnemy or TargetType.AnyAlly or TargetType.AnyPlayer;

    internal static bool Eligible(TargetType type, Creature owner, Creature candidate) => type switch
    {
        TargetType.AnyEnemy => candidate.Side != owner.Side,
        TargetType.AnyAlly => candidate.Side == owner.Side && candidate != owner && candidate.IsPlayer,
        TargetType.AnyPlayer => candidate.Side == owner.Side && candidate.IsPlayer,
        _ => false,
    };

    internal static bool Supported(TargetType type) => Manual(type) ||
        type is TargetType.Self or TargetType.None or TargetType.AllEnemies or TargetType.AllAllies
            or TargetType.RandomEnemy or TargetType.TargetedNoCreature;
}
