using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

internal sealed class SamplingChoiceAudit(
    CardModel[] candidates, CardModel[] selected, int[] upgradeLevels, object rngBefore)
{
    internal static SamplingChoiceAudit Capture(CombatState combat, CardModel[] candidates, CardModel[] selected) =>
        new(candidates, selected, candidates.Select(c => c.CurrentUpgradeLevel).ToArray(), DiscardAudit.Rng(combat));

    internal bool Verify(CombatState combat, List<object> log, int step, string action)
    {
        var pcs = combat.Players.Single().PlayerCombatState!;
        bool upgrade = action == "ARMAMENTS";
        var instances = selected.Select(card =>
        {
            int option = Array.FindIndex(candidates, c => ReferenceEquals(c, card));
            return new
            {
                option,
                id = card.Id.Entry,
                hand_index = Array.FindIndex(pcs.Hand.Cards.ToArray(), c => ReferenceEquals(c, card)),
                absent_from_discard = !pcs.DiscardPile.Cards.Any(c => ReferenceEquals(c, card)),
                upgrade_before = upgradeLevels[option],
                upgrade_after = card.CurrentUpgradeLevel,
            };
        }).ToArray();
        bool matched = instances.All(c => c.hand_index >= 0 && c.absent_from_discard
            && c.upgrade_after == c.upgrade_before + (upgrade ? 1 : 0));
        if (upgrade)
            matched &= candidates.Select((card, option) => (card, option)).All(x =>
                ReferenceEquals(x.card, selected.Single()) || x.card.CurrentUpgradeLevel == upgradeLevels[x.option]);
        log.Add(new { step, action, sampling_choice = matched, instances,
            rng_at_choice = rngBefore, rng_after = DiscardAudit.Rng(combat) });
        return matched;
    }
}
