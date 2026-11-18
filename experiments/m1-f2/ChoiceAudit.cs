using CombatSolver.Engine.Common;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

internal sealed class DiscardAudit(
    CardModel[] candidates, CardModel[] selected, int minimum, int maximum, object rngBefore)
{
    internal static DiscardAudit Capture(CombatState combat, CardModel[] candidates,
        CardModel[] selected, int minimum, int maximum) =>
        new(candidates, selected, minimum, maximum, Rng(combat));

    internal bool Verify(CombatState combat, List<object> log, int step, string action)
    {
        var state = combat.Players.Single().PlayerCombatState!;
        var instances = selected.Select(card => new
        {
            option = Array.FindIndex(candidates, x => ReferenceEquals(x, card)),
            discard_index = Array.FindIndex(state.DiscardPile.Cards.ToArray(), x => ReferenceEquals(x, card)),
            absent_from_hand = !state.Hand.Cards.Any(x => ReferenceEquals(x, card)),
            absent_from_exhaust = !state.ExhaustPile.Cards.Any(x => ReferenceEquals(x, card)),
            id = card.Id.Entry,
        }).ToArray();
        bool matched = instances.All(x => x.option >= 0 && x.discard_index >= 0 &&
            x.absent_from_hand && x.absent_from_exhaust);
        log.Add(new { step, action, discard = matched, minimum, maximum, instances,
            rng_at_choice = rngBefore, rng_after = Rng(combat) });
        return matched;
    }

    internal static object Rng(CombatState combat)
    {
        var rng = combat.RunState.Rng;
        return new
        {
            shuffle = rng.Shuffle.Counter(), generation = rng.CombatCardGeneration.Counter(),
            selection = rng.CombatCardSelection.Counter(), monster_ai = rng.MonsterAi.Counter(),
        };
    }
}
